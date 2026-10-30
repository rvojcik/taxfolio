"""Realized gains: FIFO matching over stored trades, currency conversion, check against IBKR."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Engine, select

from taxfolio.engine.lots import FifoResult, LotMatch, SplitInput, TradeInput, match_fifo, split_ratio
from taxfolio.fx.converter import CzkMethod, FxConverter
from taxfolio.i18n import _
from taxfolio.services import queries
from taxfolio.storage import schema

MATCHED_ASSETS = ("STK", "BOND")
PNL_TOLERANCE = Decimal("0.01")

# "... (HOOK, HOOKIPA PHARMA INC, US43906K2096)" – the ISIN of the line's own instrument
_TRAILING_ISIN = re.compile(r",\s*([A-Z]{2}[A-Z0-9]{9}[0-9])\)\s*$")


@dataclass(frozen=True)
class RealizedRow:
    match: LotMatch
    description: str
    isin: str
    cost_czk: Decimal
    proceeds_czk: Decimal
    cost_eur: Decimal
    proceeds_eur: Decimal
    sell_commission_czk: Decimal = Decimal(0)
    sell_commission_eur: Decimal = Decimal(0)

    @property
    def gross_proceeds_czk(self) -> Decimal:
        return self.proceeds_czk - self.sell_commission_czk

    @property
    def gross_proceeds_eur(self) -> Decimal:
        return self.proceeds_eur - self.sell_commission_eur

    @property
    def pnl_czk(self) -> Decimal:
        return self.proceeds_czk - self.cost_czk

    @property
    def pnl_eur(self) -> Decimal:
        return self.proceeds_eur - self.cost_eur


@dataclass(frozen=True)
class Discrepancy:
    close_ref: int
    symbol: str
    close_datetime: datetime
    ours: Decimal
    ibkr: Decimal
    detail: str = ""


@dataclass
class FifoReport:
    result: FifoResult
    descriptions: dict[str, str]
    trades_by_ref: dict[int, queries.TradeRow]


def _trade_key(t: queries.TradeRow) -> str:
    return t.isin or f"SYM:{t.symbol}"


def load_splits(engine: Engine, account_id: str | None = None) -> tuple[list[SplitInput], list[str]]:
    ca = schema.corporate_action
    q = select(ca)
    if account_id:
        q = q.where(ca.c.account_id == account_id)
    groups: dict[object, list] = defaultdict(list)
    with engine.connect() as conn:
        for r in conn.execute(q).mappings():
            groups[r["action_id"] or (r["action_datetime"], r["description"].split(" (")[0])].append(r)

    splits: list[SplitInput] = []
    warnings: list[str] = []
    for rows in groups.values():
        desc = rows[0]["description"]
        ratio = split_ratio(desc)
        if ratio is None:
            warnings.append(_("Korporátní akce zatím není podporována: {action}").format(action=desc))
            continue

        def isin_of(r: dict) -> str:
            m = _TRAILING_ISIN.search(r["description"])
            return (m.group(1) if m else None) or r["isin"] or f"SYM:{r['symbol']}"

        new_rows = [r for r in rows if r["quantity"] > 0]
        old_rows = [r for r in rows if r["quantity"] < 0]
        new_key = isin_of(new_rows[0]) if new_rows else isin_of(rows[0])
        old_key = isin_of(old_rows[0]) if old_rows else new_key
        splits.append(SplitInput(rows[0]["action_datetime"], old_key, new_key, ratio, desc))
    return splits, warnings


def compute_fifo(
    engine: Engine, account_id: str | None = None, extra_trades: Sequence[TradeInput] = ()
) -> FifoReport:
    """FIFO over stored trades; ``extra_trades`` adds hypothetical ones (sale simulation)."""
    trades = [
        t
        for asset in MATCHED_ASSETS
        for t in queries.list_trades(engine, account_id=account_id, asset_class=asset)
    ]
    # Executions of one order share a timestamp; IBKR's lot order follows its execution order,
    # which is the trade id order (database id as fallback for Activity Statement rows).
    trades.sort(key=lambda t: (t.trade_datetime, int(t.trade_id) if t.trade_id else 0, t.id))
    inputs = [
        TradeInput(
            ref=t.id,
            key=_trade_key(t),
            symbol=t.symbol,
            currency=t.currency,
            trade_datetime=t.trade_datetime,
            quantity=t.quantity,
            proceeds=t.proceeds,
            commission=t.commission,
            commission_currency=t.commission_currency,
        )
        for t in trades
    ]
    inputs.extend(extra_trades)
    splits, split_warnings = load_splits(engine, account_id)
    result = match_fifo(inputs, splits)
    result.warnings[:0] = split_warnings
    descriptions = {_trade_key(t): t.description for t in trades}
    return FifoReport(result, descriptions, {t.id: t for t in trades})


def realized_rows(
    report: FifoReport, fx: FxConverter, czk_method: CzkMethod | None = None, year: int | None = None
) -> list[RealizedRow]:
    rows = []
    for m in report.result.matches:
        if year and m.close_datetime.year != year:
            continue
        open_day, close_day = m.open_datetime.date(), m.close_datetime.date()
        rows.append(
            RealizedRow(
                match=m,
                description=report.descriptions.get(m.key, ""),
                isin=m.key if not m.key.startswith("SYM:") else "",
                cost_czk=fx.to_czk(m.cost, m.currency, open_day, czk_method),
                proceeds_czk=fx.to_czk(m.proceeds, m.currency, close_day, czk_method),
                cost_eur=fx.to_eur(m.cost, m.currency, open_day),
                proceeds_eur=fx.to_eur(m.proceeds, m.currency, close_day),
                sell_commission_czk=fx.to_czk(m.sell_commission, m.currency, close_day, czk_method),
                sell_commission_eur=fx.to_eur(m.sell_commission, m.currency, close_day),
            )
        )
    return rows


def check_against_ibkr(engine: Engine, report: FifoReport) -> list[Discrepancy]:
    """Compare our FIFO with IBKR: realized P/L per execution and lot open dates per sale."""
    ours: dict[int, Decimal] = defaultdict(Decimal)
    our_lots: dict[tuple[str, datetime], list[tuple[date, Decimal]]] = defaultdict(list)
    for m in report.result.matches:
        ours[m.close_ref] += m.pnl
        our_lots[(m.key, m.close_datetime)].append((m.open_datetime.date(), m.quantity))

    out: list[Discrepancy] = []
    for ref, pnl in ours.items():
        t = report.trades_by_ref[ref]
        if t.realized_pnl is not None and abs(pnl - t.realized_pnl) > PNL_TOLERANCE:
            out.append(
                Discrepancy(ref, t.symbol, t.trade_datetime, pnl, t.realized_pnl, _("realizovaný P/L"))
            )

    cl = schema.closed_lot
    ibkr_lots: dict[tuple[str, datetime], list[tuple[date, Decimal]]] = defaultdict(list)
    with engine.connect() as conn:
        for r in conn.execute(
            select(cl.c.isin, cl.c.symbol, cl.c.close_datetime, cl.c.open_datetime, cl.c.quantity)
        ):
            ibkr_lots[(r.isin or f"SYM:{r.symbol}", r.close_datetime)].append(
                (r.open_datetime.date(), r.quantity)
            )
    for key, lots in ibkr_lots.items():
        mine = our_lots.get(key)
        if mine is None:
            continue
        if _qty_by_date(mine) != _qty_by_date(lots):
            ref = next(m.close_ref for m in report.result.matches if (m.key, m.close_datetime) == key)
            t = report.trades_by_ref[ref]
            out.append(
                Discrepancy(
                    ref,
                    t.symbol,
                    key[1],
                    Decimal(0),
                    Decimal(0),
                    _("loty: {ours} vs IBKR {ibkr}").format(ours=sorted(mine), ibkr=sorted(lots)),
                )
            )
    return out


def _qty_by_date(lots: list[tuple[date, Decimal]]) -> dict[date, Decimal]:
    acc: dict[date, Decimal] = defaultdict(Decimal)
    for d, q in lots:
        acc[d] += q
    return {d: q.normalize() for d, q in acc.items()}

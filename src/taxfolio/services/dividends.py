"""Dividend events: payments grouped with their withholding tax and later corrections."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, select

from taxfolio.domain.models import CashType
from taxfolio.i18n import _
from taxfolio.storage import schema

INCOME_TYPES = (CashType.DIVIDEND.value, CashType.PAYMENT_IN_LIEU.value)


@dataclass
class DividendEvent:
    key: str
    symbol: str
    isin: str
    country: str
    currency: str
    pay_date: date
    ex_date: date | None = None
    gross: Decimal = Decimal(0)
    withheld: Decimal = Decimal(0)  # positive = tax paid
    description: str = ""
    # (date, amount) of every withholding row incl. reversals, for per-day currency conversion
    tax_rows: list[tuple[date, Decimal]] = field(default_factory=list)
    income_rows: list[tuple[date, Decimal]] = field(default_factory=list)
    payment_in_lieu: bool = False

    @property
    def withholding_rate(self) -> Decimal:
        return self.withheld / self.gross if self.gross else Decimal(0)


def _country_lookup(engine: Engine) -> tuple[dict[str, str], dict[str, str]]:
    inst, div = schema.instrument, schema.dividend_detail
    by_conid: dict[str, str] = {}
    by_isin: dict[str, str] = {}
    with engine.connect() as conn:
        for r in conn.execute(select(inst.c.conid, inst.c.isin, inst.c.issuer_country)):
            if r.issuer_country:
                if r.conid:
                    by_conid[r.conid] = r.issuer_country
                if r.isin:
                    by_isin[r.isin] = r.issuer_country
        # The Dividend Report carries IBKR's own source-country attribution; it wins.
        for conid, country in conn.execute(select(div.c.conid, div.c.country)):
            if country:
                by_conid[conid] = country
    return by_conid, by_isin


def load_dividends(
    engine: Engine, account_id: str | None = None, year: int | None = None
) -> tuple[list[DividendEvent], list[str]]:
    """All dividend events; warnings (unmatched withholding) only for ``year`` when given."""
    ct = schema.cash_transaction
    q = select(ct).where(ct.c.type.in_([*INCOME_TYPES, CashType.WITHHOLDING_TAX.value])).order_by(ct.c.date)
    if account_id:
        q = q.where(ct.c.account_id == account_id)
    by_conid, by_isin = _country_lookup(engine)

    events: dict[str, DividendEvent] = {}
    orphans: list[dict[str, Any]] = []
    with engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(q).mappings()]

    def key_of(r: dict[str, Any]) -> str:
        # Flex links a dividend and its tax through actionID; Activity Statements only by text.
        if r["action_id"]:
            return f"A:{r['action_id']}"
        base = r["description"].split(" - ")[0].split(" (")[0].upper()
        return f"D:{r['isin']}:{r['date']}:{base}"

    for r in rows:
        if r["type"] not in INCOME_TYPES:
            continue
        k = key_of(r)
        ev = events.get(k)
        if ev is None:
            isin = r["isin"] or ""
            country = by_conid.get(r["conid"] or "") or by_isin.get(isin) or (isin[:2] if isin else "")
            ev = events[k] = DividendEvent(
                key=k,
                symbol=r["symbol"] or "",
                isin=isin,
                country=country,
                currency=r["currency"],
                pay_date=r["date"],
                ex_date=r["ex_date"],
                description=r["description"],
                payment_in_lieu=r["type"] == CashType.PAYMENT_IN_LIEU.value,
            )
        ev.gross += r["amount"]
        ev.income_rows.append((r["date"], r["amount"]))

    for r in rows:
        if r["type"] != CashType.WITHHOLDING_TAX.value:
            continue
        ev = events.get(key_of(r))
        if ev is None:
            # Withholding on credit interest belongs to interest income, not to a dividend
            if "INTEREST" not in r["description"].upper() and (year is None or r["date"].year == year):
                orphans.append(r)
            continue
        ev.withheld -= r["amount"]
        ev.tax_rows.append((r["date"], -r["amount"]))

    warnings = [
        _("Srážková daň bez dividendy v datech: {day} {description} {amount} {currency}").format(
            day=r["date"], description=r["description"], amount=r["amount"], currency=r["currency"]
        )
        for r in orphans
    ]
    return sorted(events.values(), key=lambda e: e.pay_date), warnings


def by_country(events: list[DividendEvent]) -> dict[str, list[DividendEvent]]:
    out: dict[str, list[DividendEvent]] = defaultdict(list)
    for e in events:
        out[e.country].append(e)
    return dict(out)

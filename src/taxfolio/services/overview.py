"""Overview figures for the summary tab, converted to one display currency."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import Engine, select

from taxfolio.domain.models import CashType
from taxfolio.engine.exit_classifier import REASON_LABELS, TradeReason
from taxfolio.fx.converter import FxConverter, MissingRateError
from taxfolio.i18n import _
from taxfolio.services import dividends, queries, rates_service, realized
from taxfolio.storage import schema

ZERO = Decimal(0)
DISPLAY_CURRENCIES = ("CZK", "EUR", "USD")
TOP_N = 10
# Longer periods are shown per quarter, very long ones per year, so the time axis stays readable
MAX_MONTH_BARS = 18
MAX_QUARTER_BARS = 24


@dataclass(frozen=True)
class ReasonStats:
    reason: TradeReason
    count: int
    pnl: Decimal

    @property
    def label(self) -> str:
        return _(REASON_LABELS[self.reason] or "Neurčeno")


@dataclass
class CompanyDividends:
    """Dividends received from one company (all payments in the period)."""

    symbol: str
    name: str
    isin: str
    country: str
    payments: int = 0
    gross: Decimal = ZERO
    withheld: Decimal = ZERO

    @property
    def net(self) -> Decimal:
        return self.gross - self.withheld


@dataclass
class Overview:
    currency: str
    year: int | None
    realized_gains: Decimal = ZERO
    realized_losses: Decimal = ZERO
    closed_trades: int = 0
    winning_trades: int = 0
    dividends_gross: Decimal = ZERO
    withholding: Decimal = ZERO
    fees: Decimal = ZERO
    deposits: Decimal = ZERO
    withdrawals: Decimal = ZERO
    portfolio_value: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    portfolio_as_of: date | None = None
    monthly_pnl: list[tuple[str, Decimal]] = field(default_factory=list)
    monthly_dividends: list[tuple[str, Decimal]] = field(default_factory=list)
    # deposits positive, withdrawals negative (same periods as the charts above)
    monthly_deposits: list[tuple[str, Decimal]] = field(default_factory=list)
    monthly_withdrawals: list[tuple[str, Decimal]] = field(default_factory=list)
    pnl_by_symbol: list[tuple[str, Decimal]] = field(default_factory=list)
    holdings: list[tuple[str, Decimal]] = field(default_factory=list)
    reasons: list[ReasonStats] = field(default_factory=list)
    dividends_by_company: list[CompanyDividends] = field(default_factory=list)  # largest first
    warnings: list[str] = field(default_factory=list)

    @property
    def realized_pnl(self) -> Decimal:
        return self.realized_gains + self.realized_losses

    @property
    def dividends_net(self) -> Decimal:
        return self.dividends_gross - self.withholding

    @property
    def net_deposits(self) -> Decimal:
        return self.deposits + self.withdrawals

    @property
    def win_rate(self) -> Decimal | None:
        return Decimal(self.winning_trades) / self.closed_trades if self.closed_trades else None


class _Money:
    """Convert any amount to the display currency (CZK via ČNB, EUR/USD via ECB)."""

    def __init__(self, fx: FxConverter, target: str):
        self.fx, self.target = fx, target

    def __call__(self, amount: Decimal, currency: str, day: date) -> Decimal:
        if not amount or currency == self.target:
            return amount
        if self.target == "CZK":
            return self.fx.to_czk(amount, currency, day)
        eur = self.fx.to_eur(amount, currency, day)
        return eur if self.target == "EUR" else eur * self.fx.ecb_rate(self.target, day)


def _months(year: int | None, days: list[date]) -> list[str]:
    """Continuous month axis: the whole year, or first → last month with any activity."""
    if year is not None:
        return [f"{year}-{m:02d}" for m in range(1, 13)]
    if not days:
        return []
    start, end = min(days), max(days)
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _bucket(series: list[tuple[str, Decimal]]) -> list[tuple[str, Decimal]]:
    """Keep months, or sum them into quarters ('Q1/25') or years ('2025') when there are too many bars."""
    if len(series) <= MAX_MONTH_BARS:
        return series
    by_year = len(series) > MAX_QUARTER_BARS * 3
    buckets: dict[str, Decimal] = {}
    for month, value in series:
        y, m = month.split("-")
        key = y if by_year else f"Q{(int(m) - 1) // 3 + 1}/{y[2:]}"
        buckets[key] = buckets.get(key, ZERO) + value
    return list(buckets.items())


def _top(values: dict[str, Decimal], key: object = abs) -> list[tuple[str, Decimal]]:
    """Top N by the key; the rest folds into 'Ostatní' so the bar count stays bounded."""
    ordered = sorted(values.items(), key=lambda kv: key(kv[1]), reverse=True)  # type: ignore[operator]
    top, rest = ordered[:TOP_N], ordered[TOP_N:]
    if rest:
        top.append((_("Ostatní"), sum((v for _name, v in rest), ZERO)))
    return top


def build_overview(
    engine: Engine, year: int | None, currency: str = "CZK", account_id: str | None = None
) -> Overview:
    years = queries.available_years(engine)
    rates_service.ensure_rates(engine, {*years, *([year] if year else [])})
    fx = rates_service.load_converter(engine)
    money = _Money(fx, currency)
    ov = Overview(currency, year)

    def in_scope(day: date) -> bool:
        return year is None or day.year == year

    def convert(amount: Decimal, ccy: str, day: date) -> Decimal | None:
        """One missing rate must not take the whole overview down – skip the item, warn once."""
        try:
            return money(amount, ccy, day)
        except MissingRateError as exc:
            if str(exc) not in ov.warnings:
                ov.warnings.append(str(exc))
            return None

    # --- realized P/L, per sale, per month, per symbol, per exit reason
    fifo = realized.compute_fifo(engine, account_id)
    per_close: dict[int, Decimal] = defaultdict(Decimal)
    by_month: dict[str, Decimal] = defaultdict(Decimal)
    by_symbol: dict[str, Decimal] = defaultdict(Decimal)
    sale_days: list[date] = []
    for m in fifo.result.matches:
        day = m.close_datetime.date()
        if not in_scope(day):
            continue
        proceeds = convert(m.proceeds, m.currency, day)
        cost = convert(m.cost, m.currency, m.open_datetime.date())
        if proceeds is None or cost is None:
            continue
        pnl = proceeds - cost
        per_close[m.close_ref] += pnl
        by_month[f"{day:%Y-%m}"] += pnl
        by_symbol[m.symbol] += pnl
        sale_days.append(day)
    reasons: dict[TradeReason, list[Decimal]] = defaultdict(list)
    for ref, pnl in per_close.items():
        if pnl >= 0:
            ov.realized_gains += pnl
        else:
            ov.realized_losses += pnl
        reasons[fifo.trades_by_ref[ref].reason].append(pnl)
    ov.closed_trades = len(per_close)
    ov.winning_trades = sum(1 for p in per_close.values() if p > 0)
    ov.reasons = sorted(
        (ReasonStats(r, len(v), sum(v, ZERO)) for r, v in reasons.items()), key=lambda s: -s.count
    )
    ov.pnl_by_symbol = _top(by_symbol)

    # --- dividends
    events, _warnings = dividends.load_dividends(engine, account_id)
    names = _instrument_names(engine)
    companies: dict[str, CompanyDividends] = {}
    div_month: dict[str, Decimal] = defaultdict(Decimal)
    div_days: list[date] = []
    for e in events:
        if not in_scope(e.pay_date):
            continue
        parts = [convert(a, e.currency, d) for d, a in e.income_rows]
        taxes = [convert(a, e.currency, d) for d, a in e.tax_rows]
        if None in parts or None in taxes:
            continue
        gross = sum((p for p in parts if p is not None), ZERO)
        tax = sum((t for t in taxes if t is not None), ZERO)
        ov.dividends_gross += gross
        ov.withholding += tax
        div_month[f"{e.pay_date:%Y-%m}"] += gross
        div_days.append(e.pay_date)
        # One company per ISIN, so listing aliases (EXSA / EXSAd) do not split it
        key = e.isin or e.symbol
        company = companies.get(key)
        if company is None:
            company = companies[key] = CompanyDividends(
                e.symbol, names.get(e.isin or f"SYM:{e.symbol}", "") or e.symbol, e.isin, e.country
            )
        company.payments += 1
        company.gross += gross
        company.withheld += tax
    ov.dividends_by_company = sorted(companies.values(), key=lambda c: c.gross, reverse=True)

    # --- cash: fees, deposits, commissions
    ct = schema.cash_transaction
    q = select(ct.c.type, ct.c.currency, ct.c.date, ct.c.amount).where(
        ct.c.type.in_([CashType.FEE.value, CashType.DEPOSIT.value, CashType.WITHDRAWAL.value])
    )
    if account_id:
        q = q.where(ct.c.account_id == account_id)
    with engine.connect() as conn:
        cash_rows = list(conn.execute(q))
    deposit_month: dict[str, Decimal] = defaultdict(Decimal)
    withdrawal_month: dict[str, Decimal] = defaultdict(Decimal)
    activity_days: list[date] = [*sale_days, *div_days]
    for kind, ccy, day, amount in cash_rows:
        if not in_scope(day):
            continue
        activity_days.append(day)
        value = convert(amount, ccy, day)
        if value is None:
            continue
        if kind == CashType.FEE.value:
            ov.fees -= value
        elif kind == CashType.DEPOSIT.value:
            ov.deposits += value
            deposit_month[f"{day:%Y-%m}"] += value
        else:
            ov.withdrawals += value
            withdrawal_month[f"{day:%Y-%m}"] += value
    for t in fifo.trades_by_ref.values():
        day = t.trade_datetime.date()
        if not in_scope(day):
            continue
        activity_days.append(day)  # purchases too: the time axis starts with the first activity
        if t.commission and (fee := convert(t.commission, t.commission_currency, day)):
            ov.fees -= fee

    months = _months(year, activity_days)
    ov.monthly_pnl = _bucket([(mth, by_month.get(mth, ZERO)) for mth in months])
    ov.monthly_dividends = _bucket([(mth, div_month.get(mth, ZERO)) for mth in months])
    ov.monthly_deposits = _bucket([(mth, deposit_month.get(mth, ZERO)) for mth in months])
    ov.monthly_withdrawals = _bucket([(mth, withdrawal_month.get(mth, ZERO)) for mth in months])

    _portfolio(engine, ov, convert, year, account_id)
    return ov


def _instrument_names(engine: Engine) -> dict[str, str]:
    """Company name by ISIN, or by symbol for brokers without ISINs (XTB)."""
    i = schema.instrument
    out: dict[str, str] = {}
    with engine.connect() as conn:
        for isin, symbol, name in conn.execute(select(i.c.isin, i.c.symbol, i.c.description)):
            if name:
                out[isin or f"SYM:{symbol}"] = name
    return out


def _portfolio(
    engine: Engine,
    ov: Overview,
    convert: Callable[[Decimal, str, date], Decimal | None],
    year: int | None,
    account_id: str | None,
) -> None:
    """Holdings at the last statement date within the scope (Open Positions, summary level)."""
    op = schema.open_position
    q = select(op.c.as_of).where(op.c.level == "SUMMARY")
    if year is not None:
        q = q.where(op.c.as_of <= date(year, 12, 31))
    if account_id:
        q = q.where(op.c.account_id == account_id)
    with engine.connect() as conn:
        as_of = conn.execute(q.order_by(op.c.as_of.desc()).limit(1)).scalar_one_or_none()
        if as_of is None:
            return
        rows_q = select(op.c.symbol, op.c.currency, op.c.value, op.c.unrealized_pnl).where(
            op.c.level == "SUMMARY", op.c.as_of == as_of
        )
        if account_id:
            rows_q = rows_q.where(op.c.account_id == account_id)
        rows = conn.execute(rows_q).all()
    values: dict[str, Decimal] = defaultdict(Decimal)
    unrealized = ZERO
    for symbol, ccy, value, upnl in rows:
        v, u = convert(value, ccy, as_of), convert(upnl, ccy, as_of)
        if v is None or u is None:
            continue
        values[symbol] += v
        unrealized += u
    ov.portfolio_as_of = as_of
    ov.portfolio_value = sum(values.values(), ZERO)
    ov.unrealized_pnl = unrealized
    ov.holdings = _top(values, key=lambda v: v)

"""'What if I sell now' – tax impact of a hypothetical sale in CZ and SK."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import Engine, select

from taxfolio.engine.lots import Lot, LotMatch, TradeInput
from taxfolio.fx.converter import CzkMethod, FxConverter
from taxfolio.i18n import _
from taxfolio.services import queries, rates_service, realized
from taxfolio.services.tax_sk import listing_exchanges
from taxfolio.storage import schema
from taxfolio.tax.cz import compute_cz, time_test_date
from taxfolio.tax.rules_loader import CzRules, MissingRulesError, SkRules, load_cz, load_sk
from taxfolio.tax.sk import compute_sk

SIMULATED_REF = -1
FUTURE_RATE_GAP_DAYS = 3650
# Timeline: at most this many sale dates (each one is a full FIFO + tax run)
MAX_TIMELINE_POINTS = 24
# How far back to look for the latest known rules when a future year has none yet
RULES_FALLBACK_YEARS = 5


@dataclass
class Holding:
    key: str
    symbol: str
    description: str
    currency: str
    quantity: Decimal
    lots: list[Lot] = field(default_factory=list)
    last_price: Decimal | None = None
    last_price_date: date | None = None

    @property
    def label(self) -> str:
        return _("{symbol} – {name} ({quantity} ks)").format(
            symbol=self.symbol, name=self.description, quantity=f"{self.quantity.normalize():f}"
        )


@dataclass(frozen=True)
class SimulatedLot:
    match: LotMatch
    pnl_czk: Decimal
    pnl_eur: Decimal
    cz_exempt_from: date
    sk_exempt_from: date
    sk_regulated: bool

    @property
    def cz_exempt(self) -> bool:
        return self.match.close_datetime.date() >= self.cz_exempt_from

    @property
    def sk_exempt(self) -> bool:
        return self.sk_regulated and self.match.close_datetime.date() >= self.sk_exempt_from


@dataclass
class Simulation:
    holding: Holding
    quantity: Decimal
    price: Decimal
    sale_date: date
    lots: list[SimulatedLot]
    cz_tax_before: Decimal
    cz_tax_after: Decimal
    sk_tax_before: Decimal
    sk_tax_after: Decimal
    sk_health_before: Decimal
    sk_health_after: Decimal
    cz_limit_applies_after: bool
    notes: list[str] = field(default_factory=list)

    @property
    def cz_delta(self) -> Decimal:
        return self.cz_tax_after - self.cz_tax_before

    @property
    def sk_delta(self) -> Decimal:
        return (self.sk_tax_after + self.sk_health_after) - (self.sk_tax_before + self.sk_health_before)


def holdings(engine: Engine, account_id: str | None = None) -> list[Holding]:
    fifo = realized.compute_fifo(engine, account_id)
    by_key: dict[str, Holding] = {}
    for lot in fifo.result.open_lots:
        h = by_key.get(lot.key)
        if h is None:
            h = by_key[lot.key] = Holding(
                lot.key, lot.symbol, fifo.descriptions.get(lot.key, ""), lot.currency, Decimal(0)
            )
        h.quantity += lot.quantity
        h.lots.append(lot)
    prices = last_prices(engine)
    for h in by_key.values():
        if h.key in prices:
            h.last_price_date, h.last_price = prices[h.key]
    return sorted(by_key.values(), key=lambda h: h.symbol)


def last_prices(engine: Engine) -> dict[str, tuple[date, Decimal]]:
    """Latest mark price per ISIN from the statements' open positions."""
    op = schema.open_position
    out: dict[str, tuple[date, Decimal]] = {}
    with engine.connect() as conn:
        rows = conn.execute(
            select(op.c.isin, op.c.as_of, op.c.close_price).where(
                op.c.level == "SUMMARY", op.c.isin.is_not(None)
            )
        )
        for isin, as_of, price in rows:
            if isin not in out or as_of > out[isin][0]:
                out[isin] = (as_of, price)
    return out


def simulate_sale(
    engine: Engine,
    holding: Holding,
    quantity: Decimal,
    price: Decimal,
    sale_date: date,
    czk_method: CzkMethod | None = None,
    commission: Decimal = Decimal(0),
    account_id: str | None = None,
    fx: FxConverter | None = None,
) -> Simulation:
    """``fx``: reuse an already loaded converter (loading it is the slow part)."""
    if quantity <= 0 or quantity > holding.quantity:
        raise ValueError(
            _("Množství musí být mezi 0 a {maximum}").format(maximum=f"{holding.quantity.normalize():f}")
        )
    year = sale_date.year
    rule_notes: list[str] = []
    cz_rules = _rules_for(load_cz, "CZ", year, rule_notes)
    sk_rules = _rules_for(load_sk, "SK", year, rule_notes)
    if fx is None:
        fx = load_fx(engine, year)

    sale = TradeInput(
        ref=SIMULATED_REF,
        key=holding.key,
        symbol=holding.symbol,
        currency=holding.currency,
        # after any real trade of that day
        trade_datetime=datetime.combine(sale_date, time(23, 59, 59)),
        quantity=-quantity,
        proceeds=quantity * price,
        commission=-abs(commission),
        commission_currency=holding.currency,
    )
    before = realized.compute_fifo(engine, account_id)
    after = realized.compute_fifo(engine, account_id, [sale])
    rows_before = realized.realized_rows(before, fx, czk_method, year)
    rows_after = realized.realized_rows(after, fx, czk_method, year)
    exchanges = listing_exchanges(engine)

    cz_b = compute_cz(year, cz_rules, czk_method, rows_before, [], fx)
    cz_a = compute_cz(year, cz_rules, czk_method, rows_after, [], fx)
    sk_b = compute_sk(year, sk_rules, rows_before, [], fx, exchanges)
    sk_a = compute_sk(year, sk_rules, rows_after, [], fx, exchanges)

    regulated = (exchanges.get(holding.key) or "").upper() in sk_rules.regulated_exchanges
    lots = [
        SimulatedLot(
            match=r.match,
            pnl_czk=r.pnl_czk,
            pnl_eur=r.pnl_eur,
            cz_exempt_from=time_test_date(r.match.open_datetime.date(), cz_rules.time_test_years),
            sk_exempt_from=time_test_date(r.match.open_datetime.date(), sk_rules.time_test_years),
            sk_regulated=regulated,
        )
        for r in rows_after
        if r.match.close_ref == SIMULATED_REF
    ]
    sim = Simulation(
        holding=holding,
        quantity=quantity,
        price=price,
        sale_date=sale_date,
        lots=lots,
        cz_tax_before=cz_b.tax_securities,
        cz_tax_after=cz_a.tax_securities,
        sk_tax_before=sk_b.tax_securities,
        sk_tax_after=sk_a.tax_securities,
        sk_health_before=sk_b.health_insurance,
        sk_health_after=sk_a.health_insurance,
        cz_limit_applies_after=cz_a.securities.limit_applies,
    )
    sim.notes = _advice(sim) + rule_notes
    return sim


def load_fx(engine: Engine, year: int) -> FxConverter:
    rates_service.ensure_rates(engine, {*queries.available_years(engine), year, date.today().year})
    fx = rates_service.load_converter(engine)
    fx.max_gap_days = FUTURE_RATE_GAP_DAYS
    return fx


def _rules_for[R: (CzRules, SkRules)](
    load: Callable[[int], R], country: str, year: int, notes: list[str]
) -> R:
    """Rules of ``year``, or the latest known ones for a future year that has none yet."""
    for candidate in range(year, year - RULES_FALLBACK_YEARS - 1, -1):
        try:
            rules = load(candidate)
        except MissingRulesError:
            continue
        if candidate != year:
            notes.append(
                _("{country}: pravidla pro rok {year} zatím nejsou, použita pravidla roku {used}.").format(
                    country=country, year=year, used=candidate
                )
            )
        return rules
    return load(year)  # raises MissingRulesError with the file name


@dataclass(frozen=True)
class ImpactPoint:
    """Tax impact of the same sale made on another day."""

    sale_date: date
    cz_delta: Decimal
    sk_delta: Decimal
    reason: str


def impact_timeline(
    engine: Engine,
    sim: Simulation,
    commission: Decimal = Decimal(0),
    czk_method: CzkMethod | None = None,
    account_id: str | None = None,
) -> list[ImpactPoint]:
    """The sale on the chosen day and on each later day the tax changes: a sold lot passes the
    CZ or SK time test, or a new tax year starts (other sales of the year no longer count)."""
    start = sim.sale_date
    reasons: dict[date, list[str]] = defaultdict(list)
    reasons[start].append(_("zvolené datum"))
    for lot in sim.lots:
        if lot.match.pnl <= 0:
            continue  # waiting changes nothing for a lot sold at a loss
        if lot.cz_exempt_from > start:
            reasons[lot.cz_exempt_from].append(_("ČR: časový test"))
        if lot.sk_regulated and lot.sk_exempt_from > start:
            reasons[lot.sk_exempt_from].append(_("SR: časový test"))
    last = max(reasons)
    for year in range(start.year + 1, last.year + 1):
        reasons[date(year, 1, 1)].append(_("nový rok"))
    days = sorted(set(reasons))[:MAX_TIMELINE_POINTS]

    fx = load_fx(engine, max(days).year)
    out = []
    for day in days:
        point = (
            sim
            if day == start
            else simulate_sale(
                engine, sim.holding, sim.quantity, sim.price, day, czk_method, commission, account_id, fx
            )
        )
        out.append(ImpactPoint(day, point.cz_delta, point.sk_delta, ", ".join(dict.fromkeys(reasons[day]))))
    return out


def _advice(sim: Simulation) -> list[str]:
    notes = []
    waiting: dict[str, list[tuple[date, Decimal]]] = defaultdict(list)
    for lot in sim.lots:
        if lot.match.pnl > 0 and not lot.cz_exempt:
            waiting["CZ"].append((lot.cz_exempt_from, lot.match.quantity))
        if lot.match.pnl > 0 and lot.sk_regulated and not lot.sk_exempt:
            waiting["SK"].append((lot.sk_exempt_from, lot.match.quantity))
    for country, items in waiting.items():
        last = max(d for d, _ in items)
        qty = sum((q for _, q in items), Decimal(0))
        notes.append(
            _(
                "{country}: {quantity} ks v zisku ještě nesplňuje časový test – plně osvobozeno od {day}."
            ).format(country=country, quantity=f"{qty.normalize():f}", day=f"{last:%d.%m.%Y}")
        )
    losses = [lot for lot in sim.lots if lot.match.pnl < 0]
    if losses:
        notes.append(
            _(
                "Prodej obsahuje ztrátové loty – v ČR i SR snižují zdanitelný zisk jen v témže roce "
                "(jinak propadnou)."
            )
        )
    if sim.cz_limit_applies_after:
        notes.append(_("ČR: celkové příjmy z prodejů v roce zůstávají do 100 000 Kč – vše osvobozeno."))
    if sim.sale_date > date.today():
        notes.append(_("Prodej v budoucnu: kurzy měn odhadnuty posledním známým kurzem."))
    return notes

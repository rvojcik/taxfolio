"""Assemble the Slovak tax report from stored data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Engine, select

from taxfolio.engine.lots import Lot
from taxfolio.fx.converter import FxConverter, MissingRateError
from taxfolio.services import dividends, queries, rates_service, realized
from taxfolio.services.tax_cz import rate_warnings, scope_warnings
from taxfolio.storage import schema
from taxfolio.tax.cz import time_test_date
from taxfolio.tax.rules_loader import SkRules, load_sk
from taxfolio.tax.sk import SkTaxReport, compute_sk


@dataclass(frozen=True)
class SkTimeTestLot:
    lot: Lot
    description: str
    exempt_from: date
    regulated: bool
    cost_eur: Decimal | None


def listing_exchanges(engine: Engine) -> dict[str, str | None]:
    """Instrument key (ISIN, or ``SYM:symbol`` without one, as in FIFO) → listing exchange."""
    i = schema.instrument
    with engine.connect() as conn:
        rows = conn.execute(select(i.c.isin, i.c.symbol, i.c.listing_exchange)).all()
    return {isin or f"SYM:{symbol}": exch for isin, symbol, exch in rows}


def build_sk_report(
    engine: Engine, year: int, account_id: str | None = None, exemption_used_elsewhere: bool = False
) -> tuple[SkTaxReport, list[SkTimeTestLot]]:
    rules = load_sk(year)
    rates_service.ensure_rates(engine, {*queries.available_years(engine), year})
    fx = rates_service.load_converter(engine)
    fifo = realized.compute_fifo(engine, account_id)
    # CZK method is irrelevant here; the EUR side of each row uses ECB rates.
    rows = realized.realized_rows(fifo, fx, None, year)
    events, div_warnings = dividends.load_dividends(engine, account_id, year)
    exchanges = listing_exchanges(engine)
    report = compute_sk(year, rules, rows, events, fx, exchanges, exemption_used_elsewhere)
    report.warnings[:0] = div_warnings + fifo.result.warnings
    currencies = rates_service.used_currencies(engine)
    report.rates_note = fx.describe("EUR", currencies)
    report.warnings[:0] = rate_warnings(fx, "EUR", currencies)
    report.warnings[:0] = scope_warnings(engine, account_id)
    return report, time_test_calendar(fifo, fx, rules, exchanges)


def time_test_calendar(
    fifo: realized.FifoReport, fx: FxConverter, rules: SkRules, exchanges: dict[str, str | None]
) -> list[SkTimeTestLot]:
    out = []
    for lot in fifo.result.open_lots:
        opened = lot.open_datetime.date()
        try:
            cost: Decimal | None = fx.to_eur(lot.cost, lot.currency, opened)
        except MissingRateError:
            cost = None
        regulated = (exchanges.get(lot.key) or "").upper() in rules.regulated_exchanges
        out.append(
            SkTimeTestLot(
                lot,
                fifo.descriptions.get(lot.key, ""),
                time_test_date(opened, rules.time_test_years),
                regulated,
                cost,
            )
        )
    return sorted(out, key=lambda t: t.exempt_from)

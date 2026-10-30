"""Assemble the Czech tax report from stored data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Engine

from taxfolio.engine.lots import Lot
from taxfolio.fx.converter import (
    RATE_SOURCE_LABELS,
    TAX_ACCEPTED_SOURCES,
    CzkMethod,
    FxConverter,
    MissingRateError,
)
from taxfolio.i18n import _
from taxfolio.services import dividends, queries, rates_service, realized
from taxfolio.tax.cz import CzTaxReport, compute_cz, time_test_date
from taxfolio.tax.rules_loader import load_cz


@dataclass(frozen=True)
class TimeTestLot:
    lot: Lot
    description: str
    exempt_from: date
    cost_czk: Decimal | None

    @property
    def days_left(self) -> int:
        return max((self.exempt_from - date.today()).days, 0)


def build_cz_report(
    engine: Engine, year: int, method: CzkMethod | None = None, account_id: str | None = None
) -> tuple[CzTaxReport, list[TimeTestLot]]:
    """``method=None`` converts each currency by the source chosen in the settings."""
    rules = load_cz(year)
    rates_service.ensure_rates(engine, {*queries.available_years(engine), year})
    fx = rates_service.load_converter(engine)
    fifo = realized.compute_fifo(engine, account_id)
    rows = realized.realized_rows(fifo, fx, method, year)
    events, div_warnings = dividends.load_dividends(engine, account_id, year)
    report = compute_cz(year, rules, method, rows, events, fx)
    report.warnings[:0] = div_warnings + fifo.result.warnings
    currencies = rates_service.used_currencies(engine)
    if method is None:
        report.rates_note = fx.describe("CZK", currencies)
        report.warnings[:0] = rate_warnings(fx, "CZK", currencies)
    else:
        report.rates_note = (
            _("jednotný kurz (GFŘ)") if method is CzkMethod.GFR_ANNUAL else _("denní kurz ČNB")
        )
    report.warnings[:0] = scope_warnings(engine, account_id)
    return report, time_test_calendar(fifo, fx, method, rules.time_test_years)


def scope_warnings(engine: Engine, account_id: str | None) -> list[str]:
    """The tax is owed per person: limits and exemptions count all accounts together."""
    others = [a for a, _name, _ccy in queries.list_accounts(engine) if a != account_id]
    if account_id is None or not others:
        return []
    return [
        _(
            "Zobrazen jen účet {account}. Daň se počítá za všechny účty dohromady – limity a osvobození "
            "(100 000 Kč v ČR, 500 € v SR) i výsledná daň platí jen pro výběr „Všechny účty“."
        ).format(account=account_id)
    ]


def rate_warnings(fx: FxConverter, target: str, currencies: list[str]) -> list[str]:
    """Warn when the configured rates are not what the tax law of ``target``'s country accepts."""
    rules = {c: fx.rule(target, c) for c in currencies if c != target}
    out = []
    odd = sorted(c for c, r in rules.items() if r.source not in TAX_ACCEPTED_SOURCES[target])
    if odd:
        accepted = _(" nebo ").join(_(RATE_SOURCE_LABELS[s]) for s in sorted(TAX_ACCEPTED_SOURCES[target]))
        out.append(
            _(
                "Kurz pro {currencies} není podle zákona přípustný pro daňové přiznání "
                "(přípustné: {accepted}) – změňte jej v Nastavení."
            ).format(currencies=", ".join(odd), accepted=accepted)
        )
    if target == "CZK" and len({r.source for r in rules.values()}) > 1:
        out.append(
            _(
                "Pro různé měny jsou nastaveny různé zdroje kurzu – v ČR se volba kurzu uplatní "
                "jednotně pro celé zdaňovací období."
            )
        )
    return out


def time_test_calendar(
    fifo: realized.FifoReport, fx: FxConverter, method: CzkMethod | None, years: int
) -> list[TimeTestLot]:
    out = []
    for lot in fifo.result.open_lots:
        opened = lot.open_datetime.date()
        try:
            cost_czk: Decimal | None = fx.to_czk(lot.cost, lot.currency, opened, method)
        except MissingRateError:
            cost_czk = None
        out.append(
            TimeTestLot(lot, fifo.descriptions.get(lot.key, ""), time_test_date(opened, years), cost_czk)
        )
    return sorted(out, key=lambda t: t.exempt_from)

"""Load yearly tax rules from ``tax/rules/<country>/<year>.yaml`` (ARCHITEKTURA.md §4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from importlib import resources
from typing import Any

import yaml

from taxfolio.i18n import _


class MissingRulesError(LookupError):
    pass


def _dec(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


@dataclass(frozen=True)
class CzRules:
    year: int
    sources: list[str]
    time_test_years: int
    time_test_cap: Decimal | None
    gross_income_limit: Decimal
    limit_includes_time_tested: bool
    rate: Decimal
    higher_rate: Decimal
    higher_rate_threshold: Decimal
    domestic_country: str
    domestic_rate: Decimal
    treaty_rates: dict[str, Decimal] = field(default_factory=dict)
    exempt_notification_limit: Decimal = Decimal(5_000_000)

    def treaty_rate(self, country: str) -> Decimal:
        return self.treaty_rates.get(country, self.treaty_rates["default"])


def load_raw(country: str, year: int) -> dict[str, Any]:
    ref = resources.files("taxfolio.tax.rules") / country.lower() / f"{year}.yaml"
    if not ref.is_file():
        raise MissingRulesError(
            _("Chybí daňová pravidla pro {country} {year} ({file})").format(
                country=country, year=year, file=f"tax/rules/{country.lower()}/{year}.yaml"
            )
        )
    data: dict[str, Any] = yaml.safe_load(ref.read_text(encoding="utf-8"))
    if data.get("country") != country.upper() or data.get("year") != year:
        raise ValueError(f"Soubor pravidel {country}/{year} má nesouhlasnou hlavičku")
    return data


def load_cz(year: int) -> CzRules:
    d = load_raw("CZ", year)
    sec, tax, div = d["securities"], d["income_tax"], d["dividends"]
    treaty = {k: Decimal(str(v)) for k, v in div["treaty_rates"].items()}
    if "default" not in treaty:
        raise ValueError(f"CZ {year}: treaty_rates musí obsahovat 'default'")
    return CzRules(
        year=year,
        sources=list(d.get("sources", [])),
        time_test_years=int(sec["time_test_years"]),
        time_test_cap=_dec(sec.get("time_test_cap")),
        gross_income_limit=Decimal(str(sec["gross_income_limit"])),
        limit_includes_time_tested=bool(sec["limit_includes_time_tested"]),
        rate=Decimal(str(tax["rate"])),
        higher_rate=Decimal(str(tax["higher_rate"])),
        higher_rate_threshold=Decimal(str(tax["higher_rate_threshold"])),
        domestic_country=div["domestic_country"],
        domestic_rate=Decimal(str(div["domestic_rate"])),
        treaty_rates=treaty,
        exempt_notification_limit=Decimal(str(d["exempt_notification_limit"])),
    )


@dataclass(frozen=True)
class Bracket:
    up_to: Decimal | None
    rate: Decimal


@dataclass(frozen=True)
class SkRules:
    year: int
    sources: list[str]
    time_test_years: int
    require_regulated_market: bool
    exemption: Decimal
    brackets: list[Bracket]
    health_rate: Decimal
    profit_year_rates: list[tuple[int, int | None, Decimal]]
    non_cooperating_rate: Decimal
    non_cooperating_states: frozenset[str]
    treaty_rates: dict[str, Decimal]
    fx_rate_day: str
    regulated_exchanges: frozenset[str]

    def treaty_rate(self, country: str) -> Decimal:
        return self.treaty_rates.get(country, self.treaty_rates["default"])

    def dividend_rate(self, country: str, profit_year: int) -> Decimal | None:
        """Slovak rate for a foreign dividend; ``None`` = profit year not subject to tax."""
        if country in self.non_cooperating_states:
            return self.non_cooperating_rate
        for start, end, rate in self.profit_year_rates:
            if start <= profit_year and (end is None or profit_year <= end):
                return rate
        return None

    def income_tax(self, base: Decimal) -> Decimal:
        tax, lower = Decimal(0), Decimal(0)
        for b in self.brackets:
            upper = base if b.up_to is None else min(base, b.up_to)
            if upper > lower:
                tax += (upper - lower) * b.rate
            if b.up_to is None or base <= b.up_to:
                break
            lower = b.up_to
        return tax


def load_sk(year: int) -> SkRules:
    d = load_raw("SK", year)
    sec, div = d["securities"], d["dividends"]
    treaty = {k: Decimal(str(v)) for k, v in div["treaty_rates"].items()}
    if "default" not in treaty:
        raise ValueError(f"SK {year}: treaty_rates musí obsahovať 'default'")
    return SkRules(
        year=year,
        sources=list(d.get("sources", [])),
        time_test_years=int(sec["time_test_years"]),
        require_regulated_market=bool(sec["require_regulated_market"]),
        exemption=Decimal(str(sec["exemption"])),
        brackets=[Bracket(_dec(b["up_to"]), Decimal(str(b["rate"]))) for b in d["income_tax"]["brackets"]],
        health_rate=Decimal(str(d["health_insurance"]["rate"])),
        profit_year_rates=[
            (int(r["from"]), r["to"], Decimal(str(r["rate"]))) for r in div["profit_year_rates"]
        ],
        non_cooperating_rate=Decimal(str(div["non_cooperating_rate"])),
        non_cooperating_states=frozenset(div.get("non_cooperating_states") or []),
        treaty_rates=treaty,
        fx_rate_day=d["fx"]["rate_day"],
        regulated_exchanges=frozenset(d["regulated_exchanges"]),
    )

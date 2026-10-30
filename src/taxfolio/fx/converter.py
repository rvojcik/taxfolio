"""Currency conversion for tax purposes.

CZ (§ 38 ZDP): either the ČNB rate valid on the transaction day (``CNB_DAILY``) or the unified
annual rate (``GFR_ANNUAL``) – the average of ČNB rates on the last day of each month of the year,
which is how the GFŘ computes the published table (verified for 2024 and 2025: EUR 25.16/24.66,
USD 23.28/21.84). On days without a fixing the last preceding fixing applies.

SK: ECB reference rate of the transaction day (last preceding publication on non-business days).

Which source applies to which currency is configurable per target currency (CZK for Czech taxes,
EUR for Slovak taxes) through ``RateRule`` – including IBKR's own daily rates and a fixed rate.
Explicitly passing a ``CzkMethod`` (CLI ``--czk``) overrides the rules.
"""

from __future__ import annotations

import bisect
import calendar
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from taxfolio.fx.sources import CNB, ECB, RateRow
from taxfolio.i18n import N_, _


class CzkMethod(StrEnum):
    CNB_DAILY = "CNB_DAILY"
    GFR_ANNUAL = "GFR_ANNUAL"


class RateSource(StrEnum):
    CNB_DAILY = "CNB_DAILY"  # ČNB fixing of the day
    GFR_ANNUAL = "GFR_ANNUAL"  # unified annual rate (average of ČNB month-end fixings)
    ECB_DAILY = "ECB_DAILY"  # ECB reference rate of the day
    IBKR_DAILY = "IBKR_DAILY"  # IBKR conversion rates from the Flex statement
    FIXED = "FIXED"  # user-entered constant


RATE_SOURCE_LABELS = {
    RateSource.CNB_DAILY: N_("ČNB – denní kurz"),
    RateSource.GFR_ANNUAL: N_("Jednotný kurz (GFŘ, roční)"),
    RateSource.ECB_DAILY: N_("ECB – denní kurz"),
    RateSource.IBKR_DAILY: N_("IBKR – kurz z výpisu"),
    RateSource.FIXED: N_("Pevný kurz"),
}

# Sources the tax law accepts for each tax currency (anything else gets a warning)
TAX_ACCEPTED_SOURCES = {
    "CZK": frozenset({RateSource.CNB_DAILY, RateSource.GFR_ANNUAL}),
    "EUR": frozenset({RateSource.ECB_DAILY}),
}
DEFAULT_SOURCES = {"CZK": RateSource.CNB_DAILY, "EUR": RateSource.ECB_DAILY}
TARGET_CURRENCIES = ("CZK", "EUR")


@dataclass(frozen=True)
class RateRule:
    source: RateSource
    fixed: Decimal | None = None  # target units per 1 unit of the currency (FIXED only)


class MissingRateError(LookupError):
    pass


class FxConverter:
    def __init__(
        self,
        rows: Iterable[RateRow],
        unified_overrides: dict[tuple[str, int], Decimal] | None = None,
        max_gap_days: int = 10,
        rules: dict[tuple[str, str], RateRule] | None = None,
        ibkr_rows: Iterable[tuple[date, str, str, Decimal]] = (),
    ):
        # (target, currency) → rule; missing entries use DEFAULT_SOURCES
        self.rules = dict(rules or {})
        # How far a missing day may fall back to the last published rate. The sale simulator
        # raises it so that a future date uses the latest known rate.
        self.max_gap_days = max_gap_days
        series: dict[tuple[str, str], list[tuple[date, Decimal]]] = defaultdict(list)
        for r in rows:
            series[(r.source, r.currency)].append((r.date, r.rate))
        self._dates: dict[tuple[str, str], list[date]] = {}
        self._rates: dict[tuple[str, str], list[Decimal]] = {}
        for key, points in series.items():
            points.sort()
            self._dates[key] = [d for d, _ in points]
            self._rates[key] = [r for _, r in points]
        self._unified_overrides = unified_overrides or {}
        self._unified_cache: dict[tuple[str, int], Decimal] = {}
        # IBKR publishes "1 FROM = rate TO" per day, all quoted to the account base currency
        ibkr: dict[tuple[str, str], list[tuple[date, Decimal]]] = defaultdict(list)
        for day, from_ccy, to_ccy, rate in ibkr_rows:
            ibkr[(from_ccy, to_ccy)].append((day, rate))
        for (from_ccy, to_ccy), points in ibkr.items():
            points.sort()
            key = (f"IBKR>{to_ccy}", from_ccy)
            self._dates[key] = [d for d, _ in points]
            self._rates[key] = [r for _, r in points]
        self._ibkr_bases = sorted({to for _, to in ibkr})

    def _rate_on(self, source: str, currency: str, day: date) -> Decimal:
        key = (source, currency)
        dates = self._dates.get(key)
        if not dates:
            raise MissingRateError(
                _("Chybí kurzy {source} pro {currency}").format(source=source, currency=currency)
            )
        i = bisect.bisect_right(dates, day) - 1
        if i < 0 or (day - dates[i]).days > self.max_gap_days:
            raise MissingRateError(
                _("Chybí kurz {source} {currency} k {day}").format(
                    source=source, currency=currency, day=f"{day:%d.%m.%Y}"
                )
            )
        return self._rates[key][i]

    # --- CZK -------------------------------------------------------------------------------

    def cnb_rate(self, currency: str, day: date) -> Decimal:
        """CZK per 1 unit of ``currency`` valid on ``day``."""
        return Decimal(1) if currency == "CZK" else self._rate_on(CNB, currency, day)

    def unified_rate(self, currency: str, year: int) -> Decimal:
        if currency == "CZK":
            return Decimal(1)
        key = (currency, year)
        if key in self._unified_overrides:
            return self._unified_overrides[key]
        if key not in self._unified_cache:
            month_ends = [date(year, m, calendar.monthrange(year, m)[1]) for m in range(1, 13)]
            avg = sum((self.cnb_rate(currency, d) for d in month_ends), Decimal(0)) / 12
            self._unified_cache[key] = avg.quantize(Decimal("0.01"), ROUND_HALF_UP)
        return self._unified_cache[key]

    def czk_rate(self, currency: str, day: date, method: CzkMethod | None = None) -> Decimal:
        """CZK per unit; ``method`` overrides the configured rule (CLI), ``None`` follows the rules."""
        if method is None:
            return self.rate(currency, day, "CZK")
        # CzkMethod(...) also accepts the plain string a Qt combo box hands back
        if CzkMethod(method) is CzkMethod.GFR_ANNUAL:
            return self.unified_rate(currency, day.year)
        return self.cnb_rate(currency, day)

    def to_czk(self, amount: Decimal, currency: str, day: date, method: CzkMethod | None = None) -> Decimal:
        return amount * self.czk_rate(currency, day, method)

    # --- EUR -------------------------------------------------------------------------------

    def ecb_rate(self, currency: str, day: date) -> Decimal:
        """Units of ``currency`` per 1 EUR on ``day``."""
        return Decimal(1) if currency == "EUR" else self._rate_on(ECB, currency, day)

    def to_eur(self, amount: Decimal, currency: str, day: date) -> Decimal:
        return amount * self.rate(currency, day, "EUR")

    # --- configurable sources ----------------------------------------------------------------

    def rule(self, target: str, currency: str) -> RateRule:
        return self.rules.get((target, currency)) or RateRule(DEFAULT_SOURCES[target])

    def rate(self, currency: str, day: date, target: str, source: RateSource | None = None) -> Decimal:
        """``target`` units per 1 unit of ``currency`` using the configured (or given) source."""
        if currency == target:
            return Decimal(1)
        rule = self.rule(target, currency) if source is None else RateRule(source)
        src = rule.source
        if src is RateSource.FIXED:
            if source is not None or rule.fixed is None:
                # a preview of FIXED without a value, or a rule saved without one
                raise MissingRateError(
                    _("Pevný kurz {currency}/{target} není zadán").format(currency=currency, target=target)
                )
            return rule.fixed
        if src is RateSource.CNB_DAILY:
            return self._via_czk(lambda c: self.cnb_rate(c, day), currency, target)
        if src is RateSource.GFR_ANNUAL:
            return self._via_czk(lambda c: self.unified_rate(c, day.year), currency, target)
        if src is RateSource.ECB_DAILY:
            # ECB quotes units per 1 EUR
            return self.ecb_rate(target, day) / self.ecb_rate(currency, day)
        return self._ibkr_rate(currency, target, day)

    @staticmethod
    def _via_czk(czk_per_unit: Callable[[str], Decimal], currency: str, target: str) -> Decimal:
        return czk_per_unit(currency) / czk_per_unit(target)

    def _ibkr_rate(self, currency: str, target: str, day: date) -> Decimal:
        for base in self._ibkr_bases:

            def to_base(c: str, base: str = base) -> Decimal:
                return Decimal(1) if c == base else self._rate_on(f"IBKR>{base}", c, day)

            try:
                return to_base(currency) / to_base(target)
            except MissingRateError:
                continue
        raise MissingRateError(
            _("Chybí kurz IBKR {currency}/{target} k {day} (importujte Flex Query)").format(
                currency=currency, target=target, day=f"{day:%d.%m.%Y}"
            )
        )

    def latest_date(self, source: RateSource, currency: str) -> date | None:
        """Last day with a published rate for ``currency`` in ``source`` (for previews)."""
        keys = {
            RateSource.CNB_DAILY: [(CNB, currency)],
            RateSource.GFR_ANNUAL: [(CNB, currency)],
            RateSource.ECB_DAILY: [(ECB, currency)],
            RateSource.IBKR_DAILY: [(f"IBKR>{b}", currency) for b in self._ibkr_bases],
        }.get(source, [])
        days = [self._dates[k][-1] for k in keys if self._dates.get(k)]
        return max(days) if days else None

    def describe(self, target: str, currencies: Iterable[str]) -> str:
        """Short human summary of the rules in force, e.g. 'USD: ČNB – denní kurz; EUR: pevný 25'."""
        parts = []
        for ccy in sorted(set(currencies) - {target}):
            r = self.rule(target, ccy)
            label = (
                _("pevný {rate}").format(rate=r.fixed)
                if r.source is RateSource.FIXED
                else _(RATE_SOURCE_LABELS[r.source])
            )
            parts.append(f"{ccy}: {label}")
        return "; ".join(parts)

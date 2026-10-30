"""Slovak personal income tax on investments (ZDP 595/2003 Z. z.).

Securities (§ 8 ods. 1 písm. e): a lot is exempt when held for more than one year and admitted
to a regulated (also foreign) market. Taxable sales are summed (income − expenses); a negative
total is ignored, and up to 500 € of a positive total is exempt. Exempt sales cannot offset
taxable ones. Taxable § 8 income is also subject to health insurance (estimate only).

Foreign dividends (§ 51e, osobitný základ dane): taxed at the rate for the year in which the
profit was reported – by default the year before payment; foreign tax is credited up to the
treaty rate and up to the Slovak tax.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from taxfolio.fx.converter import FxConverter
from taxfolio.i18n import N_, _
from taxfolio.services.dividends import DividendEvent
from taxfolio.services.realized import RealizedRow
from taxfolio.tax.cz import DividendPayment, FormLine, time_test_date
from taxfolio.tax.rules_loader import SkRules

ZERO = Decimal(0)
EXEMPT_TIME_TEST = N_("1 rok + regulovaný trh")  # translate with _() when displayed


@dataclass(frozen=True)
class SkSaleLine:
    row: RealizedRow
    exempt_from: date
    regulated: bool
    income: Decimal  # EUR, gross sale price
    expenses: Decimal  # EUR, cost incl. buy and sell commission

    @property
    def taxable(self) -> bool:
        return not (self.regulated and self.row.match.close_datetime.date() >= self.exempt_from)

    @property
    def result(self) -> Decimal:
        return self.income - self.expenses


@dataclass
class SkSecurities:
    exempt_income: Decimal = ZERO
    taxable_income: Decimal = ZERO
    taxable_expenses: Decimal = ZERO
    gains: Decimal = ZERO
    losses: Decimal = ZERO
    exemption_used: Decimal = ZERO

    @property
    def difference(self) -> Decimal:
        return self.taxable_income - self.taxable_expenses

    @property
    def base(self) -> Decimal:
        """Základ dane z § 8 after ignoring a loss and the 500 € exemption."""
        return max(self.difference, ZERO) - self.exemption_used


@dataclass(frozen=True)
class SkDividendLine:
    country: str
    profit_year: int
    rate: Decimal | None  # None = not subject to Slovak tax
    count: int
    gross: Decimal
    withheld: Decimal
    treaty_rate: Decimal

    @property
    def sk_tax(self) -> Decimal:
        return ZERO if self.rate is None else self.gross * self.rate

    @property
    def credit(self) -> Decimal:
        if self.rate is None:
            return ZERO
        return min(self.withheld, self.gross * self.treaty_rate, self.sk_tax)

    @property
    def tax_due(self) -> Decimal:
        return self.sk_tax - self.credit


@dataclass
class SkTaxReport:
    year: int
    rules: SkRules
    sales: list[SkSaleLine]
    securities: SkSecurities
    dividends: list[SkDividendLine]
    exemption_used_elsewhere: bool
    warnings: list[str] = field(default_factory=list)
    payments: list[DividendPayment] = field(default_factory=list)
    rates_note: str = ""

    @property
    def tax_securities(self) -> Decimal:
        return self.rules.income_tax(self.securities.base)

    @property
    def health_insurance(self) -> Decimal:
        return self.securities.base * self.rules.health_rate

    @property
    def dividend_gross(self) -> Decimal:
        return sum((d.gross for d in self.dividends if d.rate is not None), ZERO)

    @property
    def dividend_tax(self) -> Decimal:
        return sum((d.sk_tax for d in self.dividends), ZERO)

    @property
    def credit(self) -> Decimal:
        return sum((d.credit for d in self.dividends), ZERO)

    @property
    def tax_total(self) -> Decimal:
        return self.tax_securities + self.dividend_tax - self.credit

    def form_lines(self) -> list[FormLine]:
        s = self.securities
        lines = [
            FormLine(
                _("DP typ B, VI. oddíl (§ 8)"),
                _("Příjmy z prodeje cenných papírů"),
                s.taxable_income,
                _("jen zdanitelné prodeje (bez osvobozených)"),
            ),
            FormLine(
                _("DP typ B, VI. oddíl (§ 8)"),
                _("Výdaje"),
                s.taxable_expenses,
                _("pořizovací cena + poplatky; ztráta se neuvádí"),
            ),
            FormLine(
                _("DP typ B, VI. oddíl (§ 8)"),
                _("Osvobození (§ 9 odst. 1 písm. i)"),
                s.exemption_used,
                _("max. 500 € spolu s jinými příjmy podle § 8"),
            ),
            FormLine(_("DP typ B, VI. oddíl (§ 8)"), _("Dílčí základ daně § 8"), s.base),
        ]
        for d in sorted(self.dividends, key=lambda d: -d.gross):
            if d.rate is None:
                continue
            label = _("Příloha č. 2 – dividendy {country} (zisk {year}, {rate})").format(
                country=d.country, year=d.profit_year, rate=f"{d.rate:.0%}"
            )
            lines.append(FormLine(label, _("Zvláštní základ daně"), d.gross))
            lines.append(
                FormLine(
                    label,
                    _("Daň zaplacená v zahraničí k zápočtu"),
                    d.credit,
                    _("sraženo {withheld}, max. {rate} podle smlouvy").format(
                        withheld=f"{d.withheld:.2f}", rate=f"{d.treaty_rate:.0%}"
                    ),
                )
            )
        return lines


def compute_sk(
    year: int,
    rules: SkRules,
    realized: list[RealizedRow],
    dividends: list[DividendEvent],
    fx: FxConverter,
    listing_exchanges: dict[str, str | None],
    exemption_used_elsewhere: bool = False,
    profit_year_overrides: dict[str, int] | None = None,
) -> SkTaxReport:
    warnings: list[str] = []
    sales, securities = _securities(
        [r for r in realized if r.match.close_datetime.year == year],
        rules,
        listing_exchanges,
        exemption_used_elsewhere,
        warnings,
    )
    payments: list[DividendPayment] = []
    divs = _dividends(
        [d for d in dividends if d.pay_date.year == year],
        rules,
        fx,
        profit_year_overrides or {},
        warnings,
        payments,
    )
    if securities.base > 0:
        warnings.append(
            _(
                "Zdravotní pojištění z § 8 (odhad {rate}): {amount} € – vyměří pojišťovna v ročním "
                "zúčtování; sazbu ověřte."
            ).format(rate=f"{rules.health_rate:.0%}", amount=f"{securities.base * rules.health_rate:,.2f}")
        )
    if len(rules.brackets) > 1:
        warnings.append(
            _(
                "Daň je počítána jen ze základu z investic; s jinými příjmy (mzda) může překročit hranici "
                "{threshold} € a část se zdaní vyšší sazbou."
            ).format(threshold=f"{rules.brackets[0].up_to:,.2f}")
        )
    if rules.fx_rate_day != "same":
        warnings.append(_("Kurz ECB se bere z předchozího dne (nastavení pravidel)."))
    return SkTaxReport(year, rules, sales, securities, divs, exemption_used_elsewhere, warnings, payments)


def _eur(fx: FxConverter, amount: Decimal, currency: str, day: date, rules: SkRules) -> Decimal:
    if rules.fx_rate_day == "previous":
        day -= timedelta(days=1)
    return fx.to_eur(amount, currency, day)


def _securities(
    rows: list[RealizedRow],
    rules: SkRules,
    listing_exchanges: dict[str, str | None],
    exemption_used_elsewhere: bool,
    warnings: list[str],
) -> tuple[list[SkSaleLine], SkSecurities]:
    s = SkSecurities()
    sales = []
    unknown_exchange: set[str] = set()
    for r in rows:
        exchange = listing_exchanges.get(r.match.key)
        regulated = (
            not rules.require_regulated_market or (exchange or "").upper() in rules.regulated_exchanges
        )
        if rules.require_regulated_market and not regulated:
            unknown_exchange.add(f"{r.match.symbol} ({exchange or '?'})")
        line = SkSaleLine(
            row=r,
            exempt_from=time_test_date(r.match.open_datetime.date(), rules.time_test_years),
            regulated=regulated,
            income=r.gross_proceeds_eur,
            expenses=r.cost_eur - r.sell_commission_eur,
        )
        sales.append(line)
        if not line.taxable:
            s.exempt_income += line.income
            continue
        s.taxable_income += line.income
        s.taxable_expenses += line.expenses
        if line.result >= 0:
            s.gains += line.result
        else:
            s.losses += line.result
    if unknown_exchange:
        warnings.append(
            _("Burza není v seznamu regulovaných trhů – osvobození po 1 roce se neuplatnilo: {items}").format(
                items=", ".join(sorted(unknown_exchange))
            )
        )
    positive = max(s.difference, ZERO)
    s.exemption_used = ZERO if exemption_used_elsewhere else min(positive, rules.exemption)
    if s.difference < 0:
        warnings.append(
            _("Zdanitelné prodeje skončily ztrátou {amount} € – ke ztrátě se nepřihlíží.").format(
                amount=f"{s.difference:,.2f}"
            )
        )
    sales.sort(key=lambda line: line.row.match.close_datetime)
    return sales, s


def _dividends(
    events: list[DividendEvent],
    rules: SkRules,
    fx: FxConverter,
    overrides: dict[str, int],
    warnings: list[str],
    payments: list[DividendPayment],
) -> list[SkDividendLine]:
    gross: dict[tuple[str, int], Decimal] = defaultdict(Decimal)
    withheld: dict[tuple[str, int], Decimal] = defaultdict(Decimal)
    count: dict[tuple[str, int], int] = defaultdict(int)
    for e in events:
        profit_year = overrides.get(e.key, e.pay_date.year - 1)
        key = (e.country or "??", profit_year)
        g = sum((_eur(fx, a, e.currency, d, rules) for d, a in e.income_rows), ZERO)
        w = sum((_eur(fx, a, e.currency, d, rules) for d, a in e.tax_rows), ZERO)
        payments.append(DividendPayment(e, g, w, profit_year))
        gross[key] += g
        withheld[key] += w
        count[key] += 1
    lines = []
    for country, profit_year in sorted(gross):
        rate = rules.dividend_rate(country, profit_year)
        line = SkDividendLine(
            country,
            profit_year,
            rate,
            count[(country, profit_year)],
            gross[(country, profit_year)],
            withheld[(country, profit_year)],
            rules.treaty_rate(country),
        )
        lines.append(line)
        if rate is None:
            warnings.append(
                _("Dividendy {country} ze zisku {year} nejsou předmětem daně v SR.").format(
                    country=country, year=profit_year
                )
            )
    return lines

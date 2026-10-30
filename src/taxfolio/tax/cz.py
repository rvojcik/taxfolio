"""Czech personal income tax on investments (ZDP 586/1992 Sb.).

Securities (§ 10): each FIFO lot is tested separately. If the year's gross sale income does not
exceed the limit (100 000 Kč), every sale is exempt (§ 4 odst. 1 písm. t). Otherwise lots held
longer than the time test (3 years, § 4 odst. 1 písm. u) are exempt and the rest is taxed:
income − expenses across all taxable sales, a negative total counts as zero (losses do not carry
forward and do not reduce other income).

Dividends (§ 8): domestic (CZ) dividends are taxed by final withholding and stay out of the return.
Foreign dividends enter gross; foreign withholding is credited per country (§ 38f, simple credit)
up to the treaty rate and up to the Czech tax on that income.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from taxfolio.fx.converter import CzkMethod, FxConverter
from taxfolio.i18n import N_, _
from taxfolio.services.dividends import DividendEvent
from taxfolio.services.realized import RealizedRow
from taxfolio.tax.rules_loader import CzRules

ZERO = Decimal(0)
# Ignore rounding noise when warning about foreign tax above the treaty rate
NOT_CREDITABLE_MIN = Decimal(10)
# Czech source texts (translate with _() when displayed)
EXEMPT_TIME_TEST = N_("časový test")
EXEMPT_LIMIT = N_("limit příjmů")


def add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 Feb → 28 Feb
        return d.replace(year=d.year + years, day=28)


def time_test_date(opened: date, years: int) -> date:
    """First day on which a sale is exempt: the holding must *exceed* ``years``."""
    return date.fromordinal(add_years(opened, years).toordinal() + 1)


@dataclass(frozen=True)
class SaleLine:
    row: RealizedRow
    exempt_from: date
    exempt_reason: str | None

    @property
    def taxable(self) -> bool:
        return self.exempt_reason is None


@dataclass
class SecuritiesSummary:
    gross_income: Decimal = ZERO  # all sales
    limit_base: Decimal = ZERO  # amount tested against the 100k limit
    limit_applies: bool = False
    time_test_income: Decimal = ZERO
    taxable_income: Decimal = ZERO
    taxable_expenses: Decimal = ZERO
    taxable_gains: Decimal = ZERO
    taxable_losses: Decimal = ZERO

    @property
    def taxable_difference(self) -> Decimal:
        return self.taxable_income - self.taxable_expenses

    @property
    def partial_base(self) -> Decimal:
        """Dílčí základ daně § 10 from securities (a loss counts as zero)."""
        return max(self.taxable_difference, ZERO)

    @property
    def exempt_income(self) -> Decimal:
        return self.gross_income - self.taxable_income


@dataclass(frozen=True)
class DividendCountry:
    country: str
    domestic: bool
    count: int
    gross: Decimal
    withheld: Decimal
    treaty_rate: Decimal
    czech_tax: Decimal  # tax at the CZ rate on this income
    credit: Decimal  # creditable foreign tax

    @property
    def withholding_rate(self) -> Decimal:
        return self.withheld / self.gross if self.gross else ZERO

    @property
    def tax_due(self) -> Decimal:
        return ZERO if self.domestic else self.czech_tax - self.credit

    @property
    def not_creditable(self) -> Decimal:
        return ZERO if self.domestic else self.withheld - self.credit


@dataclass(frozen=True)
class DividendPayment:
    """One dividend payment converted to the tax currency (detail for the attachment)."""

    event: DividendEvent
    gross: Decimal
    withheld: Decimal
    profit_year: int | None = None  # SK only


@dataclass(frozen=True)
class FormLine:
    form: str
    label: str
    value: Decimal
    note: str = ""


@dataclass
class CzTaxReport:
    year: int
    method: CzkMethod | None  # None = rates per currency from the settings
    rules: CzRules
    sales: list[SaleLine]
    securities: SecuritiesSummary
    dividends: list[DividendCountry]
    warnings: list[str] = field(default_factory=list)
    payments: list[DividendPayment] = field(default_factory=list)
    rates_note: str = ""  # which exchange rates were used, for the printed attachment

    @property
    def foreign_dividends(self) -> list[DividendCountry]:
        return [d for d in self.dividends if not d.domestic]

    @property
    def foreign_dividend_income(self) -> Decimal:
        return sum((d.gross for d in self.foreign_dividends), ZERO)

    @property
    def tax_securities(self) -> Decimal:
        return self.securities.partial_base * self.rules.rate

    @property
    def tax_dividends_before_credit(self) -> Decimal:
        return sum((d.czech_tax for d in self.foreign_dividends), ZERO)

    @property
    def credit(self) -> Decimal:
        return sum((d.credit for d in self.foreign_dividends), ZERO)

    @property
    def tax_total(self) -> Decimal:
        return self.tax_securities + self.tax_dividends_before_credit - self.credit

    def tax_securities_at(self, rate: Decimal) -> Decimal:
        return self.securities.partial_base * rate

    def tax_dividends_at(self, rate: Decimal) -> Decimal:
        """Czech tax on foreign dividends at ``rate`` after the credit (capped by the tax at that rate)."""
        return sum(
            (
                d.gross * rate - min(d.withheld, d.gross * d.treaty_rate, d.gross * rate)
                for d in self.foreign_dividends
            ),
            ZERO,
        )

    def tax_total_at(self, rate: Decimal) -> Decimal:
        return self.tax_securities_at(rate) + self.tax_dividends_at(rate)

    @property
    def tax_total_higher(self) -> Decimal:
        """Estimate when the whole base falls into the higher bracket (other income above the threshold)."""
        return self.tax_total_at(self.rules.higher_rate)

    def form_lines(self) -> list[FormLine]:
        s = self.securities
        lines = [
            FormLine(
                _("Příloha č. 2, oddíl 2"),
                _("Prodej cenných papírů – příjmy"),
                s.taxable_income,
                _("jen zdanitelné prodeje (bez osvobozených)"),
            ),
            FormLine(
                _("Příloha č. 2, oddíl 2"),
                _("Prodej cenných papírů – výdaje"),
                s.taxable_expenses,
                _("pořizovací cena prodaných lotů + poplatky"),
            ),
            FormLine(
                _("Hlavní list, ř. 40"),
                _("Dílčí základ daně § 10"),
                s.partial_base,
                _("záporný rozdíl (ztráta) se uvádí jako 0"),
            ),
            FormLine(
                _("Hlavní list, ř. 38"),
                _("Dílčí základ daně § 8 – zahraniční dividendy (hrubě)"),
                self.foreign_dividend_income,
                _("alternativně samostatný základ § 16a"),
            ),
        ]
        for d in sorted(self.foreign_dividends, key=lambda d: -d.gross):
            form = _("Příloha č. 3 – stát {country}").format(country=d.country)
            lines.append(FormLine(form, _("Příjmy ze zdrojů v zahraničí"), d.gross))
            lines.append(
                FormLine(
                    form,
                    _("Daň zaplacená v zahraničí (k zápočtu)"),
                    d.credit,
                    _("sraženo {withheld}, max. {rate} dle smlouvy").format(
                        withheld=f"{d.withheld:.2f}", rate=f"{d.treaty_rate:.0%}"
                    ),
                )
            )
        return lines


def compute_cz(
    year: int,
    rules: CzRules,
    method: CzkMethod | None,
    realized: list[RealizedRow],
    dividends: list[DividendEvent],
    fx: FxConverter,
) -> CzTaxReport:
    method = None if method is None else CzkMethod(method)
    warnings: list[str] = []
    rows = [r for r in realized if r.match.close_datetime.year == year]
    sales, summary = _securities(rows, rules, warnings)
    payments: list[DividendPayment] = []
    div_lines = _dividends(
        [d for d in dividends if d.pay_date.year == year], rules, method, fx, warnings, payments
    )

    exempt_total = summary.exempt_income
    if exempt_total > rules.exempt_notification_limit:
        warnings.append(
            _(
                "Osvobozené příjmy {amount} Kč přesahují {limit} Kč – povinnost oznámit osvobozené příjmy (§ 38v)."
            ).format(amount=f"{exempt_total:,.0f}", limit=f"{rules.exempt_notification_limit:,.0f}")
        )
    if summary.partial_base + sum((d.gross for d in div_lines if not d.domestic), ZERO) > 0:
        warnings.append(
            _(
                "Daň je odhadnuta sazbou {rate}. Pokud celkový základ daně včetně jiných příjmů "
                "(mzda) přesáhne {threshold} Kč, část se daní {higher_rate}."
            ).format(
                rate=f"{rules.rate:.0%}",
                threshold=f"{rules.higher_rate_threshold:,.0f}",
                higher_rate=f"{rules.higher_rate:.0%}",
            )
        )
    return CzTaxReport(year, method, rules, sales, summary, div_lines, warnings, payments)


def _securities(
    rows: list[RealizedRow], rules: CzRules, warnings: list[str]
) -> tuple[list[SaleLine], SecuritiesSummary]:
    s = SecuritiesSummary()
    time_tested: list[tuple[RealizedRow, date]] = []
    others: list[tuple[RealizedRow, date]] = []
    for r in rows:
        exempt_from = time_test_date(r.match.open_datetime.date(), rules.time_test_years)
        income = r.gross_proceeds_czk
        s.gross_income += income
        if r.match.close_datetime.date() >= exempt_from:
            s.time_test_income += income
            time_tested.append((r, exempt_from))
        else:
            others.append((r, exempt_from))

    s.limit_base = s.gross_income if rules.limit_includes_time_tested else s.gross_income - s.time_test_income
    s.limit_applies = s.limit_base <= rules.gross_income_limit
    if rules.time_test_cap is not None and s.time_test_income > rules.time_test_cap:
        warnings.append(
            _(
                "Příjmy osvobozené časovým testem {amount} Kč přesahují strop {cap} Kč (§ 4 odst. 3) – "
                "nadlimitní část není v tomto výpočtu zdaněna."
            ).format(amount=f"{s.time_test_income:,.0f}", cap=f"{rules.time_test_cap:,.0f}")
        )

    sales: list[SaleLine] = []
    for r, exempt_from in time_tested:
        sales.append(SaleLine(r, exempt_from, EXEMPT_LIMIT if s.limit_applies else EXEMPT_TIME_TEST))
    for r, exempt_from in others:
        if s.limit_applies:
            sales.append(SaleLine(r, exempt_from, EXEMPT_LIMIT))
            continue
        sales.append(SaleLine(r, exempt_from, None))
        expenses = r.cost_czk - r.sell_commission_czk  # sell commission is negative
        s.taxable_income += r.gross_proceeds_czk
        s.taxable_expenses += expenses
        pnl = r.gross_proceeds_czk - expenses
        if pnl >= 0:
            s.taxable_gains += pnl
        else:
            s.taxable_losses += pnl
    sales.sort(key=lambda line: line.row.match.close_datetime)
    if s.taxable_difference < 0:
        warnings.append(
            _(
                "Zdanitelné prodeje skončily ztrátou {amount} Kč – ztráta se neuplatní "
                "(nepřevádí se do dalších let)."
            ).format(amount=f"{s.taxable_difference:,.2f}")
        )
    return sales, s


def _dividends(
    events: list[DividendEvent],
    rules: CzRules,
    method: CzkMethod | None,
    fx: FxConverter,
    warnings: list[str],
    payments: list[DividendPayment],
) -> list[DividendCountry]:
    gross: dict[str, Decimal] = defaultdict(Decimal)
    withheld: dict[str, Decimal] = defaultdict(Decimal)
    count: dict[str, int] = defaultdict(int)
    for e in events:
        country = e.country or "??"
        if not e.country:
            warnings.append(
                _("Dividenda {symbol} {day} nemá zemi zdroje – doplňte ji.").format(
                    symbol=e.symbol, day=e.pay_date
                )
            )
        g = sum((fx.to_czk(a, e.currency, d, method) for d, a in e.income_rows), ZERO)
        w = sum((fx.to_czk(a, e.currency, d, method) for d, a in e.tax_rows), ZERO)
        payments.append(DividendPayment(e, g, w))
        gross[country] += g
        withheld[country] += w
        count[country] += 1

    lines = []
    for country in sorted(gross):
        domestic = country == rules.domestic_country
        g, w = gross[country], withheld[country]
        treaty = rules.domestic_rate if domestic else rules.treaty_rate(country)
        czech_tax = ZERO if domestic else g * rules.rate
        credit = ZERO if domestic else min(w, g * treaty, czech_tax)
        line = DividendCountry(country, domestic, count[country], g, w, treaty, czech_tax, credit)
        lines.append(line)
        if domestic and line.withholding_rate > rules.domestic_rate + Decimal("0.005"):
            warnings.append(
                _(
                    "Tuzemské dividendy ({country}) – sraženo {withheld} místo {rate} (zahraniční broker bez "
                    "doložení rezidence). Do přiznání nevstupují; o vrácení rozdílu {difference} Kč se poraďte "
                    "s daňovým poradcem."
                ).format(
                    country=country,
                    withheld=f"{line.withholding_rate:.0%}",
                    rate=f"{rules.domestic_rate:.0%}",
                    difference=f"{w - g * rules.domestic_rate:,.2f}",
                )
            )
        elif not domestic and line.not_creditable > NOT_CREDITABLE_MIN:
            warnings.append(
                _(
                    "Dividendy {country}: sraženo {withheld}, započíst lze max. {rate} – {amount} Kč lze "
                    "požadovat zpět ve státě zdroje."
                ).format(
                    country=country,
                    withheld=f"{line.withholding_rate:.1%}",
                    rate=f"{treaty:.0%}",
                    amount=f"{line.not_creditable:,.2f}",
                )
            )
    return lines

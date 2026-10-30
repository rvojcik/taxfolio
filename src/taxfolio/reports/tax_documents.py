"""Build printable tax attachments (CZ, SK) from the computed reports."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from taxfolio.fx.converter import CzkMethod
from taxfolio.i18n import N_, _
from taxfolio.reports.document import Document, Table, cents
from taxfolio.services.tax_cz import TimeTestLot
from taxfolio.services.tax_sk import SkTimeTestLot
from taxfolio.tax.cz import CzTaxReport
from taxfolio.tax.sk import SkTaxReport

DISCLAIMER = N_(
    "Podklad vypočten aplikací taxfolio z výpisů Interactive Brokers. Nejde o daňové poradenství; "
    "ověřte údaje a aktuální tiskopis před podáním."
)


def _rate(converted: Decimal, original: Decimal) -> Decimal | None:
    return (converted / original).quantize(Decimal("0.0001")) if original else None


def _amount(value: Decimal, places: int = 2) -> str:
    return f"{value:,.{places}f}"


def _headers(*texts: str) -> list[str]:
    return [_(t) for t in texts]


def cz_document(report: CzTaxReport, calendar: Sequence[TimeTestLot], account: str | None = None) -> Document:
    s = report.securities
    method = report.rates_note or (
        _("jednotný kurz (GFŘ)") if report.method == CzkMethod.GFR_ANNUAL else _("denní kurz ČNB")
    )
    doc = Document(
        title=_("Podklady k DAP FO {year} – Česká republika").format(year=report.year),
        subtitle=_("Účet: {account} · přepočet: {rates} · pravidla: {sources}").format(
            account=account or _("všechny"), rates=method, sources="; ".join(report.rules.sources)
        ),
        summary=[
            _("Úhrn příjmů z prodeje cenných papírů: {amount} Kč ({relation} limit {limit} Kč).").format(
                amount=_amount(s.gross_income),
                relation="≤" if s.limit_applies else ">",
                limit=_amount(report.rules.gross_income_limit, 0),
            ),
            _(
                "Osvobozeno časovým testem: {exempt} Kč. Zdanitelné příjmy {income} Kč, výdaje {expenses} Kč, "
                "dílčí základ § 10: {base} Kč."
            ).format(
                exempt=_amount(s.time_test_income),
                income=_amount(s.taxable_income),
                expenses=_amount(s.taxable_expenses),
                base=_amount(s.partial_base),
            ),
            _(
                "Zahraniční dividendy (hrubě): {gross} Kč, zápočet daně zaplacené v zahraničí: {credit} Kč."
            ).format(gross=_amount(report.foreign_dividend_income), credit=_amount(report.credit)),
            _("Odhad daně ({rate}): {tax} Kč.").format(
                rate=f"{report.rules.rate:.0%}", tax=_amount(report.tax_total)
            ),
            _("Odhad daně ({rate}, celý základ nad {threshold} Kč): {tax} Kč.").format(
                rate=f"{report.rules.higher_rate:.0%}",
                threshold=_amount(report.rules.higher_rate_threshold, 0),
                tax=_amount(report.tax_total_higher),
            ),
        ],
        notes=[*report.warnings, _(DISCLAIMER)],
    )
    doc.tables.append(
        Table(
            _("Do přiznání"),
            _headers("Tiskopis", "Položka", "Hodnota Kč", "Poznámka"),
            [[f.form, f.label, cents(f.value), f.note] for f in report.form_lines()],
        )
    )
    doc.tables.append(
        Table(
            _("Prodeje cenných papírů"),
            _headers(
                "Prodej",
                "Symbol",
                "Název",
                "ISIN",
                "Množství",
                "Nákup",
                "Osvobozeno od",
                "Měna",
                "Nákup (měna)",
                "Kurz nákup",
                "Prodej hrubě (měna)",
                "Kurz prodej",
                "Příjem Kč",
                "Výdaj Kč",
                "Výsledek Kč",
                "Režim",
            ),
            [
                [
                    line.row.match.close_datetime.date(),
                    line.row.match.symbol,
                    line.row.description,
                    line.row.isin,
                    line.row.match.quantity,
                    line.row.match.open_datetime.date(),
                    line.exempt_from,
                    line.row.match.currency,
                    cents(line.row.match.cost),
                    _rate(line.row.cost_czk, line.row.match.cost),
                    cents(line.row.match.gross_proceeds),
                    _rate(line.row.gross_proceeds_czk, line.row.match.gross_proceeds),
                    cents(line.row.gross_proceeds_czk),
                    cents(line.row.cost_czk - line.row.sell_commission_czk),
                    cents(line.row.pnl_czk),
                    _("zdanitelné")
                    if line.taxable
                    else _("osvobozeno – {reason}").format(reason=_(line.exempt_reason or "")),
                ]
                for line in report.sales
            ],
        )
    )
    doc.tables.append(
        Table(
            _("Dividendy podle států"),
            _headers(
                "Stát",
                "Výplat",
                "Hrubě Kč",
                "Sraženo Kč",
                "Smluvní sazba",
                "Daň ČR Kč",
                "Zápočet Kč",
                "Režim",
            ),
            [
                [
                    d.country,
                    d.count,
                    cents(d.gross),
                    cents(d.withheld),
                    f"{d.treaty_rate:.0%}",
                    cents(d.czech_tax),
                    cents(d.credit),
                    _("tuzemské – mimo DAP") if d.domestic else _("§ 8 / Příloha 3"),
                ]
                for d in report.dividends
            ],
        )
    )
    doc.tables.append(
        Table(
            _("Dividendy – jednotlivé výplaty"),
            _headers(
                "Datum",
                "Symbol",
                "ISIN",
                "Stát",
                "Měna",
                "Hrubě (měna)",
                "Sraženo (měna)",
                "Hrubě Kč",
                "Sraženo Kč",
            ),
            [
                [
                    p.event.pay_date,
                    p.event.symbol,
                    p.event.isin,
                    p.event.country,
                    p.event.currency,
                    cents(p.event.gross),
                    cents(p.event.withheld),
                    cents(p.gross),
                    cents(p.withheld),
                ]
                for p in report.payments
            ],
        )
    )
    doc.tables.append(
        Table(
            _("Otevřené pozice – časový test"),
            _headers(
                "Symbol", "Název", "Množství", "Nakoupeno", "Osvobozeno od", "Pořizovací cena", "Měna", "Kč"
            ),
            [
                [
                    t.lot.symbol,
                    t.description,
                    t.lot.quantity,
                    t.lot.open_datetime.date(),
                    t.exempt_from,
                    cents(t.lot.cost),
                    t.lot.currency,
                    cents(t.cost_czk),
                ]
                for t in calendar
            ],
        )
    )
    return doc


def sk_document(
    report: SkTaxReport, calendar: Sequence[SkTimeTestLot], account: str | None = None
) -> Document:
    s = report.securities
    doc = Document(
        title=_("Podklady k DP FO typ B {year} – Slovenská republika").format(year=report.year),
        subtitle=_("Účet: {account} · přepočet: {rates} · pravidla: {sources}").format(
            account=account or _("všechny"),
            rates=report.rates_note or _("referenční kurz ECB"),
            sources="; ".join(report.rules.sources),
        ),
        summary=[
            _("Osvobozené prodeje (držba > 1 rok, regulovaný trh): {amount} €.").format(
                amount=_amount(s.exempt_income)
            ),
            _(
                "Zdanitelné příjmy {income} €, výdaje {expenses} €, osvobození {exemption} €, "
                "dílčí základ daně § 8: {base} €."
            ).format(
                income=_amount(s.taxable_income),
                expenses=_amount(s.taxable_expenses),
                exemption=_amount(s.exemption_used),
                base=_amount(s.base),
            ),
            _("Zahraniční dividendy (zvláštní základ): {gross} €, daň {tax} €, zápočet {credit} €.").format(
                gross=_amount(report.dividend_gross),
                tax=_amount(report.dividend_tax),
                credit=_amount(report.credit),
            ),
            _("Odhad daně: {tax} €; zdravotní pojištění (odhad): {health} €.").format(
                tax=_amount(report.tax_total), health=_amount(report.health_insurance)
            ),
        ],
        notes=[*report.warnings, _(DISCLAIMER)],
    )
    doc.tables.append(
        Table(
            _("Do přiznání"),
            _headers("Tiskopis", "Položka", "Hodnota €", "Poznámka"),
            [[f.form, f.label, cents(f.value), f.note] for f in report.form_lines()],
        )
    )
    doc.tables.append(
        Table(
            _("Prodeje cenných papírů"),
            _headers(
                "Prodej",
                "Symbol",
                "Název",
                "ISIN",
                "Množství",
                "Nákup",
                "Osvobozeno od",
                "Reg. trh",
                "Měna",
                "Nákup (měna)",
                "Prodej hrubě (měna)",
                "Příjem €",
                "Výdaj €",
                "Výsledek €",
                "Režim",
            ),
            [
                [
                    line.row.match.close_datetime.date(),
                    line.row.match.symbol,
                    line.row.description,
                    line.row.isin,
                    line.row.match.quantity,
                    line.row.match.open_datetime.date(),
                    line.exempt_from,
                    _("ano") if line.regulated else _("ne"),
                    line.row.match.currency,
                    cents(line.row.match.cost),
                    cents(line.row.match.gross_proceeds),
                    cents(line.income),
                    cents(line.expenses),
                    cents(line.result),
                    _("zdanitelné") if line.taxable else _("osvobozeno"),
                ]
                for line in report.sales
            ],
        )
    )
    doc.tables.append(
        Table(
            _("Dividendy podle států"),
            _headers(
                "Stát", "Rok zisku", "Sazba SR", "Výplat", "Hrubě €", "Sraženo €", "Daň SR €", "Zápočet €"
            ),
            [
                [
                    d.country,
                    d.profit_year,
                    _("nepodléhá") if d.rate is None else f"{d.rate:.0%}",
                    d.count,
                    cents(d.gross),
                    cents(d.withheld),
                    cents(d.sk_tax),
                    cents(d.credit),
                ]
                for d in report.dividends
            ],
        )
    )
    doc.tables.append(
        Table(
            _("Dividendy – jednotlivé výplaty"),
            _headers(
                "Datum",
                "Symbol",
                "ISIN",
                "Stát",
                "Rok zisku",
                "Měna",
                "Hrubě (měna)",
                "Sraženo (měna)",
                "Hrubě €",
                "Sraženo €",
            ),
            [
                [
                    p.event.pay_date,
                    p.event.symbol,
                    p.event.isin,
                    p.event.country,
                    p.profit_year,
                    p.event.currency,
                    cents(p.event.gross),
                    cents(p.event.withheld),
                    cents(p.gross),
                    cents(p.withheld),
                ]
                for p in report.payments
            ],
        )
    )
    doc.tables.append(
        Table(
            _("Otevřené pozice – časový test"),
            _headers(
                "Symbol", "Název", "Množství", "Nakoupeno", "Osvobozeno od", "Reg. trh", "Pořizovací cena €"
            ),
            [
                [
                    t.lot.symbol,
                    t.description,
                    t.lot.quantity,
                    t.lot.open_datetime.date(),
                    t.exempt_from,
                    _("ano") if t.regulated else _("ne"),
                    cents(t.cost_eur),
                ]
                for t in calendar
            ],
        )
    )
    return doc

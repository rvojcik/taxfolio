"""Slovak tax tab: values for the return (DP typ B), sales, dividends, one-year calendar."""

from __future__ import annotations

from decimal import Decimal
from urllib.error import URLError

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QTabWidget, QVBoxLayout, QWidget
from sqlalchemy import Engine

from taxfolio.fx.converter import MissingRateError
from taxfolio.i18n import _
from taxfolio.reports.document import Document
from taxfolio.reports.tax_documents import sk_document
from taxfolio.services.tax_free import sk_tax_free
from taxfolio.services.tax_sk import SkTimeTestLot, build_sk_report
from taxfolio.tax.cz import FormLine
from taxfolio.tax.rules_loader import MissingRulesError
from taxfolio.tax.sk import EXEMPT_TIME_TEST, SkDividendLine, SkSaleLine
from taxfolio.ui.table_model import Column, RowTableModel
from taxfolio.ui.tax_cz_view import _c, _table, export_button
from taxfolio.ui.tax_free_view import TaxFreeView


def _eur(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):,.2f}".replace(",", " ") + " €"


class TaxSkView(QWidget):
    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self._engine = engine
        self._account: str | None = None
        self._year: int | None = None
        self._document: Document | None = None

        self._rates = QLabel()
        self._rates.setWordWrap(True)
        self._used_elsewhere = QCheckBox(_("Osvobození 500 € už uplatňuji u jiného příjmu podle § 8"))
        self._used_elsewhere.toggled.connect(self.refresh)
        self._headline = QLabel()
        self._headline.setTextFormat(Qt.TextFormat.RichText)
        self._headline.setWordWrap(True)
        self._warnings = QLabel()
        self._warnings.setWordWrap(True)

        self._form: RowTableModel[FormLine] = RowTableModel(
            [
                Column(_("Tiskopis"), lambda f: f.form),
                Column(_("Položka"), lambda f: f.label),
                Column(_("Hodnota (€)"), lambda f: _c(f.value)),
                Column(_("Poznámka"), lambda f: f.note),
            ]
        )
        self._sales: RowTableModel[SkSaleLine] = RowTableModel(
            [
                Column(_("Prodej"), lambda s: s.row.match.close_datetime.date()),
                Column(_("Symbol"), lambda s: s.row.match.symbol),
                Column(_("Název"), lambda s: s.row.description),
                Column(_("Množství"), lambda s: s.row.match.quantity),
                Column(_("Nákup"), lambda s: s.row.match.open_datetime.date()),
                Column(_("Osvobozeno od"), lambda s: s.exempt_from),
                Column(_("Reg. trh"), lambda s: _("ano") if s.regulated else _("ne")),
                Column(_("Příjem €"), lambda s: _c(s.income)),
                Column(_("Výdaj €"), lambda s: _c(s.expenses)),
                Column(_("Výsledek €"), lambda s: _c(s.result), signed_color=True),
                Column(
                    _("Režim"),
                    lambda s: (
                        _("zdanitelné")
                        if s.taxable
                        else _("osvobozeno ({reason})").format(reason=_(EXEMPT_TIME_TEST))
                    ),
                ),
            ]
        )
        self._divs: RowTableModel[SkDividendLine] = RowTableModel(
            [
                Column(_("Stát"), lambda d: d.country),
                Column(_("Rok zisku"), lambda d: d.profit_year),
                Column(_("Sazba SR"), lambda d: _("nepodléhá") if d.rate is None else f"{d.rate:.0%}"),
                Column(_("Výplat"), lambda d: d.count),
                Column(_("Hrubá dividenda €"), lambda d: _c(d.gross)),
                Column(_("Sraženo €"), lambda d: _c(d.withheld)),
                Column(_("Daň SR €"), lambda d: _c(d.sk_tax)),
                Column(_("Zápočet €"), lambda d: _c(d.credit)),
                Column(_("Doplatek €"), lambda d: _c(d.tax_due)),
            ]
        )
        self._calendar: RowTableModel[SkTimeTestLot] = RowTableModel(
            [
                Column(_("Symbol"), lambda t: t.lot.symbol),
                Column(_("Název"), lambda t: t.description),
                Column(_("Množství"), lambda t: t.lot.quantity),
                Column(_("Nakoupeno"), lambda t: t.lot.open_datetime.date()),
                Column(
                    _("Osvobozeno od"),
                    lambda t: t.exempt_from if t.regulated else _("nikdy (není regulovaný trh)"),
                ),
                Column(_("Pořizovací cena €"), lambda t: _c(t.cost_eur)),
            ]
        )

        inner = QTabWidget()
        summary = QWidget()
        sl = QVBoxLayout(summary)
        sl.addWidget(self._headline)
        sl.addWidget(_table(self._form, sortable=False), 1)
        sl.addWidget(self._warnings)
        inner.addTab(summary, _("Do přiznání"))
        inner.addTab(_table(self._sales), _("Prodeje"))
        inner.addTab(_table(self._divs), _("Dividendy"))
        inner.addTab(_table(self._calendar), _("Časový test (1 rok)"))
        self._tax_free = TaxFreeView(
            engine,
            sk_tax_free,
            _("SR: osvobozen je prodej po držbě delší než 1 rok, pokud je CP přijat na regulovaný trh."),
        )
        inner.addTab(self._tax_free, _("Lze prodat bez daně"))

        top = QHBoxLayout()
        top.addWidget(self._used_elsewhere)
        top.addSpacing(24)
        top.addWidget(self._rates, 1)
        top.addWidget(export_button(self, lambda: self._document, "podklady-dane-sk"))
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(inner, 1)

    def set_scope(self, account: str | None, year: int | None) -> None:
        self._account, self._year = account, year
        self.refresh()

    def _clear(self, message: str) -> None:
        self._document = None
        self._headline.setText(message)
        self._warnings.setText("")
        for model in (self._form, self._sales, self._divs, self._calendar):
            model.set_rows([])

    def refresh(self) -> None:
        self._tax_free.refresh(self._account)  # about today, whatever tax year is selected
        if self._year is None:
            self._clear(_("Vyberte zdaňovací rok v horní liště."))
            return
        try:
            report, calendar = build_sk_report(
                self._engine, self._year, self._account, self._used_elsewhere.isChecked()
            )
        except (MissingRulesError, MissingRateError, URLError, OSError) as exc:
            self._clear(f"⚠ {exc}")
            return
        self._rates.setText(
            _("Přepočet na EUR (Nastavení): {rates}").format(rates=report.rates_note or _("bez cizích měn"))
        )
        s = report.securities
        self._headline.setText(
            _(
                "<h3>Daň z příjmů FO {year} – Slovenská republika</h3>"
                "<p>Prodeje CP: osvobozeno (držba &gt; 1 rok, regulovaný trh) {exempt}; "
                "zdanitelné zisky {gains}, ztráty {losses}, osvobození {exemption} "
                "→ dílčí základ daně § 8 <b>{base}</b>.<br>"
                "Zahraniční dividendy (zvláštní základ): <b>{dividends}</b>, daň {dividend_tax}, zápočet {credit}.<br>"
                "Odhad daně: z prodejů {tax_sales} + z dividend {tax_dividends} = <b>{tax_total}</b>; "
                "zdravotní pojištění (odhad) {health}</p>"
            ).format(
                year=report.year,
                exempt=_eur(s.exempt_income),
                gains=_eur(s.gains),
                losses=_eur(s.losses),
                exemption=_eur(s.exemption_used),
                base=_eur(s.base),
                dividends=_eur(report.dividend_gross),
                dividend_tax=_eur(report.dividend_tax),
                credit=_eur(report.credit),
                tax_sales=_eur(report.tax_securities),
                tax_dividends=_eur(report.dividend_tax - report.credit),
                tax_total=_eur(report.tax_total),
                health=_eur(report.health_insurance),
            )
        )
        self._document = sk_document(report, calendar, self._account)
        self._form.set_rows(report.form_lines())
        self._sales.set_rows(report.sales)
        self._divs.set_rows(report.dividends)
        self._calendar.set_rows(calendar)
        notes = [f"⚠ {w}" for w in report.warnings]
        notes.append(
            _(
                "Rok zisku dividendy = rok výplaty − 1. Před podáním ověřte aktuální tiskopis. "
                "Aplikace je kalkulačka podkladů, ne daňové poradenství."
            )
        )
        self._warnings.setText("\n".join(notes))

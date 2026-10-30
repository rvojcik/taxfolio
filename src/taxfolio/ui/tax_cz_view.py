"""Czech tax tab: values for the return, sales, dividends by country, time-test calendar."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from urllib.error import URLError

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import Engine

from taxfolio.fx.converter import MissingRateError
from taxfolio.i18n import _
from taxfolio.reports.document import Document
from taxfolio.reports.export import export
from taxfolio.reports.tax_documents import cz_document
from taxfolio.services.tax_cz import TimeTestLot, build_cz_report
from taxfolio.tax.cz import DividendCountry, FormLine, SaleLine
from taxfolio.tax.rules_loader import MissingRulesError
from taxfolio.ui.table_model import SORT_ROLE, Column, RowTableModel


def _c(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(Decimal("0.01"))


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('1')):,}".replace(",", " ") + " Kč"


def export_button(parent: QWidget, document: Callable[[], Document | None], stem: str) -> QPushButton:
    """'Export…' button that saves the current document as XLSX or PDF."""
    button = QPushButton(_("Exportovat podklady…"))

    def run() -> None:
        doc = document()
        if doc is None:
            return
        name, _filter = QFileDialog.getSaveFileName(
            parent, _("Uložit podklady"), f"{stem}.xlsx", "Excel (*.xlsx);;PDF (*.pdf)"
        )
        if not name:
            return
        path = Path(name)
        if path.suffix.lower() not in (".xlsx", ".pdf"):
            path = path.with_suffix(".xlsx")
        try:
            export(doc, path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(parent, _("Export"), _("Export se nepodařil: {error}").format(error=exc))
            return
        QMessageBox.information(parent, _("Export"), _("Uloženo do {path}").format(path=path))

    button.clicked.connect(run)
    return button


def _table(model: RowTableModel, sortable: bool = True) -> QTableView:  # type: ignore[type-arg]
    proxy = QSortFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.setSortRole(SORT_ROLE)
    view = QTableView()
    view.setModel(proxy)
    view.setSortingEnabled(sortable)  # the form lines keep the order of the tax return
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    view.horizontalHeader().setStretchLastSection(True)
    view.verticalHeader().hide()
    return view


class TaxCzView(QWidget):
    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self._engine = engine
        self._account: str | None = None
        self._year: int | None = None
        self._document: Document | None = None

        self._rates = QLabel()
        self._rates.setWordWrap(True)
        self._headline = QLabel()
        self._headline.setTextFormat(Qt.TextFormat.RichText)
        self._headline.setWordWrap(True)
        self._warnings = QLabel()
        self._warnings.setWordWrap(True)

        self._form: RowTableModel[FormLine] = RowTableModel(
            [
                Column(_("Tiskopis"), lambda f: f.form),
                Column(_("Položka"), lambda f: f.label),
                Column(_("Hodnota (Kč)"), lambda f: _c(f.value)),
                Column(_("Poznámka"), lambda f: f.note),
            ]
        )
        self._sales: RowTableModel[SaleLine] = RowTableModel(
            [
                Column(_("Prodej"), lambda s: s.row.match.close_datetime.date()),
                Column(_("Symbol"), lambda s: s.row.match.symbol),
                Column(_("Název"), lambda s: s.row.description),
                Column(_("Množství"), lambda s: s.row.match.quantity),
                Column(_("Nákup"), lambda s: s.row.match.open_datetime.date()),
                Column(_("Osvobozeno od"), lambda s: s.exempt_from),
                Column(_("Příjem Kč"), lambda s: _c(s.row.gross_proceeds_czk)),
                Column(_("Výdaj Kč"), lambda s: _c(s.row.cost_czk - s.row.sell_commission_czk)),
                Column(_("Výsledek Kč"), lambda s: _c(s.row.pnl_czk), signed_color=True),
                Column(
                    _("Režim"),
                    lambda s: (
                        _("zdanitelné")
                        if s.taxable
                        else _("osvobozeno ({reason})").format(reason=_(s.exempt_reason or ""))
                    ),
                ),
            ]
        )
        self._divs: RowTableModel[DividendCountry] = RowTableModel(
            [
                Column(_("Stát"), lambda d: d.country),
                Column(_("Výplat"), lambda d: d.count),
                Column(_("Hrubá dividenda Kč"), lambda d: _c(d.gross)),
                Column(_("Sraženo Kč"), lambda d: _c(d.withheld)),
                Column(_("Sazba srážky"), lambda d: f"{d.withholding_rate:.1%}"),
                Column(_("Daň ČR 15 % Kč"), lambda d: _c(d.czech_tax)),
                Column(_("Zápočet Kč"), lambda d: _c(d.credit)),
                Column(_("Doplatek Kč"), lambda d: _c(d.tax_due)),
                Column(
                    _("Režim"),
                    lambda d: _("tuzemsko – srážková daň, mimo DAP") if d.domestic else _("§ 8 + Příloha 3"),
                ),
            ]
        )
        self._calendar: RowTableModel[TimeTestLot] = RowTableModel(
            [
                Column(_("Symbol"), lambda t: t.lot.symbol),
                Column(_("Název"), lambda t: t.description),
                Column(_("Množství"), lambda t: t.lot.quantity),
                Column(_("Nakoupeno"), lambda t: t.lot.open_datetime.date()),
                Column(_("Osvobozeno od"), lambda t: t.exempt_from),
                Column(_("Zbývá dní"), lambda t: t.days_left),
                Column(_("Pořizovací cena"), lambda t: _c(t.lot.cost)),
                Column(_("Měna"), lambda t: t.lot.currency),
                Column(_("Pořizovací cena Kč"), lambda t: _c(t.cost_czk)),
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
        inner.addTab(_table(self._divs), _("Dividendy podle zemí"))
        inner.addTab(_table(self._calendar), _("Časový test"))
        from taxfolio.services.tax_free import cz_tax_free
        from taxfolio.ui.tax_free_view import TaxFreeView  # imports this module's table helpers

        self._tax_free = TaxFreeView(
            engine, cz_tax_free, _("ČR: osvobozen je prodej po držbě delší než 3 roky (§ 4 odst. 1 písm. u).")
        )
        inner.addTab(self._tax_free, _("Lze prodat bez daně"))

        top = QHBoxLayout()
        top.addWidget(self._rates, 1)
        top.addWidget(export_button(self, lambda: self._document, "podklady-dane-cz"))
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
            report, calendar = build_cz_report(self._engine, self._year, None, self._account)
        except (MissingRulesError, MissingRateError, URLError, OSError) as exc:
            self._clear(f"⚠ {exc}")
            return

        self._rates.setText(
            _("Přepočet na CZK (Nastavení): {rates}").format(rates=report.rates_note or _("bez cizích měn"))
        )
        s = report.securities
        if s.limit_applies:
            regime = _("úhrn příjmů z prodeje {total} ≤ {limit} → <b>všechny prodeje osvobozeny</b>").format(
                total=_money(s.limit_base), limit=_money(report.rules.gross_income_limit)
            )
        else:
            regime = _(
                "úhrn příjmů z prodeje {total} &gt; {limit} → limit nelze použít; časovým testem osvobozeno {exempt}"
            ).format(
                total=_money(s.limit_base),
                limit=_money(report.rules.gross_income_limit),
                exempt=_money(s.time_test_income),
            )
        self._headline.setText(
            _(
                "<h3>Daň z příjmů FO {year} – Česká republika</h3>"
                "<p>Prodeje CP: {regime}.<br>"
                "Zdanitelné prodeje: zisky {gains}, ztráty {losses} → dílčí základ § 10 <b>{base}</b>.<br>"
                "Zahraniční dividendy (hrubě): <b>{dividends}</b>, zápočet zahraniční daně {credit}.<br>"
                "Odhad daně ({rate}): z prodejů {tax_sales} + z dividend {tax_dividends} = <b>{tax_total}</b><br>"
                "Odhad daně ({higher_rate}, celý základ nad {threshold}): z prodejů {tax_sales_higher} + "
                "z dividend {tax_dividends_higher} = <b>{tax_total_higher}</b></p>"
            ).format(
                year=report.year,
                regime=regime,
                gains=_money(s.taxable_gains),
                losses=_money(s.taxable_losses),
                base=_money(s.partial_base),
                dividends=_money(report.foreign_dividend_income),
                credit=_money(report.credit),
                tax_sales=_money(report.tax_securities),
                tax_dividends=_money(report.tax_dividends_before_credit - report.credit),
                tax_total=_money(report.tax_total),
                rate=f"{report.rules.rate:.0%}",
                higher_rate=f"{report.rules.higher_rate:.0%}",
                threshold=_money(report.rules.higher_rate_threshold),
                tax_sales_higher=_money(report.tax_securities_at(report.rules.higher_rate)),
                tax_dividends_higher=_money(report.tax_dividends_at(report.rules.higher_rate)),
                tax_total_higher=_money(report.tax_total_higher),
            )
        )
        self._document = cz_document(report, calendar, self._account)
        self._form.set_rows(report.form_lines())
        self._sales.set_rows(report.sales)
        self._divs.set_rows(report.dividends)
        self._calendar.set_rows(calendar)
        notes = [f"⚠ {w}" for w in report.warnings]
        notes.append(
            _(
                "Čísla řádků odpovídají tiskopisu DAP FO; před podáním ověřte aktuální verzi tiskopisu. "
                "Aplikace je kalkulačka podkladů, ne daňové poradenství."
            )
        )
        self._warnings.setText("\n".join(notes))

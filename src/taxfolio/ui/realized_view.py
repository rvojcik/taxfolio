"""Realized gains tab: FIFO-matched sales with conversion to CZK and EUR."""

from __future__ import annotations

from decimal import Decimal
from urllib.error import URLError

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import Engine

from taxfolio.fx.converter import MissingRateError
from taxfolio.i18n import _
from taxfolio.services import queries, rates_service, realized
from taxfolio.services.realized import RealizedRow
from taxfolio.ui.table_model import SORT_ROLE, Column, RowTableModel


def _rate(czk: Decimal, amount: Decimal) -> Decimal | None:
    return (czk / amount).quantize(Decimal("0.001")) if amount else None


def _cents(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):,.2f}".replace(",", " ")


class RealizedView(QWidget):
    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self._engine = engine
        self._account: str | None = None
        self._year: int | None = None

        self._rates = QLabel()
        self._rates.setWordWrap(True)
        self._search = QLineEdit()
        self._search.setPlaceholderText(_("Hledat symbol, ISIN, název…"))
        self._summary = QLabel()
        self._summary.setTextFormat(Qt.TextFormat.RichText)
        self._status = QLabel()
        self._status.setWordWrap(True)

        self._model: RowTableModel[RealizedRow] = RowTableModel(
            [
                Column(_("Prodej"), lambda r: r.match.close_datetime.date()),
                Column(_("Symbol"), lambda r: r.match.symbol),
                Column(_("Název"), lambda r: r.description),
                Column(_("ISIN"), lambda r: r.isin),
                Column(_("Množství"), lambda r: r.match.quantity),
                Column(_("Nákup"), lambda r: r.match.open_datetime.date()),
                Column(_("Držení (dny)"), lambda r: r.match.holding_days),
                Column(_("Měna"), lambda r: r.match.currency),
                Column(_("Náklad"), lambda r: _cents(r.match.cost)),
                Column(_("Výnos"), lambda r: _cents(r.match.proceeds)),
                Column(_("P/L"), lambda r: _cents(r.match.pnl), signed_color=True),
                Column(_("Kurz nákup"), lambda r: _rate(r.cost_czk, r.match.cost)),
                Column(_("Kurz prodej"), lambda r: _rate(r.proceeds_czk, r.match.proceeds)),
                Column(_("Náklad CZK"), lambda r: _cents(r.cost_czk)),
                Column(_("Výnos CZK"), lambda r: _cents(r.proceeds_czk)),
                Column(_("P/L CZK"), lambda r: _cents(r.pnl_czk), signed_color=True),
                Column(_("P/L EUR"), lambda r: _cents(r.pnl_eur), signed_color=True),
            ]
        )
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortRole(SORT_ROLE)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)
        self._search.textChanged.connect(self._proxy.setFilterFixedString)

        table = QTableView()
        table.setModel(self._proxy)
        table.setSortingEnabled(True)
        table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().hide()

        filters = QHBoxLayout()
        filters.addWidget(self._search, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(filters)
        layout.addWidget(self._rates)
        layout.addWidget(table, 1)
        layout.addWidget(self._summary)
        layout.addWidget(self._status)

    def set_scope(self, account: str | None, year: int | None) -> None:
        self._account, self._year = account, year
        self.refresh()

    def refresh(self) -> None:
        notes: list[str] = []
        years = queries.available_years(self._engine)
        try:
            fetched = rates_service.ensure_rates(self._engine, years)
            if fetched:
                notes.append(_("Staženy kurzy: {sources}").format(sources=", ".join(fetched)))
        except (URLError, OSError) as exc:
            notes.append(
                "⚠ " + _("Kurzy se nepodařilo stáhnout ({error}); použijí se uložené.").format(error=exc)
            )

        report = realized.compute_fifo(self._engine, self._account)
        fx = rates_service.load_converter(self._engine)
        currencies = rates_service.used_currencies(self._engine)
        self._rates.setText(
            _("Kurzy (Nastavení) – CZK: {czk} · EUR: {eur}").format(
                czk=fx.describe("CZK", currencies), eur=fx.describe("EUR", currencies)
            )
        )
        try:
            rows = realized.realized_rows(report, fx, None, self._year)
        except MissingRateError as exc:
            rows = []
            notes.append(f"⚠ {exc}")
        self._model.set_rows(rows)

        gains = sum((r.pnl_czk for r in rows if r.pnl_czk > 0), Decimal(0))
        losses = sum((r.pnl_czk for r in rows if r.pnl_czk < 0), Decimal(0))
        gains_eur = sum((r.pnl_eur for r in rows if r.pnl_eur > 0), Decimal(0))
        losses_eur = sum((r.pnl_eur for r in rows if r.pnl_eur < 0), Decimal(0))
        self._summary.setText(
            _(
                "<b>{count}</b> spárovaných prodejů &nbsp; | &nbsp; Zisky <b>{gains} CZK</b>, ztráty "
                "<b>{losses} CZK</b>, saldo <b>{total} CZK</b> &nbsp; | &nbsp; EUR: {gains_eur} / {losses_eur} / {total_eur}"
            ).format(
                count=len(rows),
                gains=_money(gains),
                losses=_money(losses),
                total=_money(gains + losses),
                gains_eur=_money(gains_eur),
                losses_eur=_money(losses_eur),
                total_eur=_money(gains_eur + losses_eur),
            )
        )

        discrepancies = realized.check_against_ibkr(self._engine, report)
        if discrepancies:
            notes.append(
                "⚠ "
                + _("Kontrola s IBKR: {count} rozdílů – {items}").format(
                    count=len(discrepancies),
                    items="; ".join(
                        f"{d.symbol} {d.close_datetime:%Y-%m-%d} {d.detail}" for d in discrepancies[:5]
                    ),
                )
            )
        else:
            notes.append(
                "✔ "
                + _("Kontrola s IBKR: P/L i data nákupu souhlasí ({count} párování).").format(
                    count=len(report.result.matches)
                )
            )
        notes.extend(f"⚠ {w}" for w in report.result.warnings)
        self._status.setText("\n".join(notes))

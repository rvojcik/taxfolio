"""Trade journal tab: searchable, filterable list of executions."""

from __future__ import annotations

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import Engine

from taxfolio.engine.exit_classifier import REASON_LABELS
from taxfolio.i18n import N_, _
from taxfolio.services import queries
from taxfolio.services.queries import TradeRow
from taxfolio.ui.table_model import SORT_ROLE, Column, RowTableModel

# Czech source texts, translated with _() when displayed
ASSET_FILTERS = [
    (N_("Akcie a ETF"), "STK"),
    (N_("Forex"), "CASH"),
    (N_("Dluhopisy"), "BOND"),
    (N_("Vše"), None),
]
CODE_NAMES = {
    "O": N_("otevření"),
    "C": N_("uzavření"),
    "P": N_("částečné"),
    "L": N_("likvidace IB"),
    "AFx": N_("auto FX"),
}
REASON_FILTERS = [
    (N_("Všechny důvody"), None),
    *[(label, reason) for reason, label in REASON_LABELS.items() if label],
]


def _code_text(codes: str) -> str:
    return ", ".join(_(CODE_NAMES[c]) for c in codes.split(";") if c in CODE_NAMES)


class JournalView(QWidget):
    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self._engine = engine
        self._account: str | None = None
        self._year: int | None = None

        self._asset = QComboBox()
        for label, value in ASSET_FILTERS:
            self._asset.addItem(_(label), value)
        self._asset.currentIndexChanged.connect(self.refresh)
        self._reason = QComboBox()
        for label, value in REASON_FILTERS:
            self._reason.addItem(_(label), value)
        self._reason.currentIndexChanged.connect(self.refresh)
        self._search = QLineEdit()
        self._search.setPlaceholderText(_("Hledat symbol, ISIN, název…"))
        self._summary = QLabel()

        self._model: RowTableModel[TradeRow] = RowTableModel(
            [
                Column(_("Datum"), lambda t: t.trade_datetime),
                Column(_("Směr"), lambda t: _("Nákup") if t.side == "BUY" else _("Prodej")),
                Column(_("Symbol"), lambda t: t.symbol),
                Column(_("Název"), lambda t: t.description),
                Column(_("ISIN"), lambda t: t.isin),
                Column(_("Množství"), lambda t: t.quantity),
                Column(_("Cena"), lambda t: t.price),
                Column(_("Měna"), lambda t: t.currency),
                Column(_("Objem"), lambda t: t.proceeds, signed_color=True),
                Column(_("Poplatek"), lambda t: t.commission),
                Column(_("Real. P/L (IBKR)"), lambda t: t.realized_pnl or None, signed_color=True),
                Column(_("Typ"), lambda t: _code_text(t.codes)),
                Column(_("Důvod"), lambda t: _(REASON_LABELS[t.reason]) if REASON_LABELS[t.reason] else ""),
                Column(_("Příkaz"), lambda t: t.order_type),
                Column(_("Zadán"), lambda t: t.order_time),
                Column(_("Účet"), lambda t: t.account_id),
            ]
        )
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortRole(SORT_ROLE)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)
        self._search.textChanged.connect(self._proxy.setFilterFixedString)
        self._search.textChanged.connect(self._update_summary)

        table = QTableView()
        table.setModel(self._proxy)
        table.setSortingEnabled(True)
        table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().hide()

        filters = QHBoxLayout()
        filters.addWidget(QLabel(_("Třída aktiv:")))
        filters.addWidget(self._asset)
        filters.addWidget(QLabel(_("Důvod:")))
        filters.addWidget(self._reason)
        filters.addWidget(self._search, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(filters)
        layout.addWidget(table, 1)
        layout.addWidget(self._summary)

    def set_scope(self, account: str | None, year: int | None) -> None:
        self._account, self._year = account, year
        self.refresh()

    def refresh(self) -> None:
        rows = queries.list_trades(
            self._engine, account_id=self._account, year=self._year, asset_class=self._asset.currentData()
        )
        if (reason := self._reason.currentData()) is not None:
            rows = [r for r in rows if r.reason == reason]
        self._model.set_rows(rows)
        self._update_summary()

    def _update_summary(self) -> None:
        self._summary.setText(
            _("Zobrazeno {shown} z {total} obchodů").format(
                shown=self._proxy.rowCount(), total=self._model.rowCount()
            )
        )

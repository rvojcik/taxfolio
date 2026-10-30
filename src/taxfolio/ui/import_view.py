"""Import tab: update from the input sources, add files (dialog or drag & drop), history, undo."""

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import Engine

from taxfolio.i18n import _
from taxfolio.importers import flex_web
from taxfolio.services import import_service, queries, source_sync
from taxfolio.services.flex_sync import QUERY_PERIOD, FlexPeriod, years_period
from taxfolio.services.queries import BatchRow
from taxfolio.services.source_sync import SourceResult
from taxfolio.services.sources import InputSource, load_sources
from taxfolio.ui import background
from taxfolio.ui.table_model import Column, RowTableModel
from taxfolio.ui.theme import primary

FORMAT_NAMES = {
    "ibkr_flex_xml": "Flex Query (XML)",
    "ibkr_activity_statement_csv": "Activity Statement",
    "ibkr_dividend_report_csv": "Dividend Report",
    "ibkr_fx_income_worksheet_csv": "FX Income Worksheet",
    "xtb_cash_operations": "XTB",
}


# Past years offered for download even without data in the database yet
FLEX_YEARS_OFFERED = 6
QUERY_PERIOD_KEY = "query"
SOURCES_ALL_KEY = "all"
# Imports named in the delete confirmation; the rest is summed up
MAX_LISTED = 15


class SourcesWorker(QObject):
    """Downloads from the input sources off the UI thread (IBKR may take a minute per statement)."""

    progress = Signal(str)
    finished = Signal(list)  # list[SourceResult]; importing happens back on the UI thread
    cancelled = Signal()

    def __init__(self, sources: list[InputSource], period: FlexPeriod, known: set[str]) -> None:
        super().__init__()
        self._sources, self._period, self._known = sources, period, known
        self.cancel = threading.Event()

    def run(self) -> None:
        try:
            results = source_sync.fetch_all(
                self._sources, self._period, self._known, progress=self.progress.emit, cancel=self.cancel
            )
        except source_sync.Cancelled:
            self.cancelled.emit()
            return
        if self.cancel.is_set():  # stopped while the last answer was being processed
            self.cancelled.emit()
            return
        self.finished.emit(results)


class ImportView(QWidget):
    data_changed = Signal()

    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self._engine = engine
        self._sources: list[InputSource] = []
        self.setAcceptDrops(True)

        add_btn = QPushButton(_("Přidat soubory…"))
        add_btn.clicked.connect(self._choose_files)
        self._sync_btn = primary(QPushButton(_("Aktualizovat ze zdrojů")))
        self._sync_btn.setToolTip(
            _("Stáhne a naimportuje data ze zdrojů nastavených v Nastavení → Zdroje dat.")
        )
        self._sync_btn.clicked.connect(self._sync_or_stop)
        # Which sources: SOURCES_ALL_KEY or a source id
        self._source = QComboBox()
        # "first-last" years, or QUERY_PERIOD_KEY for the period saved in the Flex Query
        # (text keys: QComboBox.findData cannot compare Python tuples)
        self._flex_period = QComboBox()
        self._flex_period.setToolTip(
            _(
                "Období pro zdroje, které stahují výpisy (IBKR). Více let se stahuje po jednom výpisu "
                "na rok (max. 365 dní na požadavek). Složky importují všechny nové soubory."
            )
        )
        self._worker: SourcesWorker | None = None  # the running update, None when idle
        self._undo_btn = QPushButton(_("Smazat vybrané importy"))
        self._undo_btn.setToolTip(
            _("Odstraní vybrané importy i záznamy, které přinesly. Více řádků vyberete s Ctrl nebo Shift.")
        )
        self._undo_btn.setEnabled(False)
        self._undo_btn.clicked.connect(self._undo_selected)
        hint = QLabel(
            _(
                "Data se aktualizují ze zdrojů nastavených v Nastavení → Zdroje dat (IBKR Flex Web Service, "
                "složky s exporty). Jednotlivé soubory (IBKR: Flex Query XML, Activity Statement, Dividend "
                "Report, FX Income Worksheet; XTB: peněžní operace CSV/XLSX) lze přidat i ručně nebo "
                "přetáhnout do okna. Opakovaný import stejných dat nevytvoří duplicity."
            )
        )
        hint.setWordWrap(True)

        self._model: RowTableModel[BatchRow] = RowTableModel(
            [
                Column("#", lambda b: b.id),
                Column(_("Importováno"), lambda b: b.imported_at),
                Column(_("Soubor"), lambda b: b.file_name),
                Column(
                    _("Typ"), lambda b: FORMAT_NAMES.get(b.source_format, b.source_format)
                ),  # product names
                Column(_("Účet"), lambda b: b.account_id),
                Column(_("Od"), lambda b: b.period_start),
                Column(_("Do"), lambda b: b.period_end),
                Column(_("Nové"), lambda b: b.rows_new),
                Column(_("Duplicitní"), lambda b: b.rows_duplicate),
                Column(_("Upozornění"), lambda b: b.warnings),
            ]
        )
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.selectionModel().selectionChanged.connect(self._selection_changed)
        delete_key = QShortcut(QKeySequence.StandardKey.Delete, self._table)
        delete_key.activated.connect(self._undo_selected)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().hide()

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(140)

        buttons = QHBoxLayout()
        buttons.addWidget(self._sync_btn)
        buttons.addWidget(QLabel(_("Zdroj:")))
        buttons.addWidget(self._source)
        buttons.addWidget(QLabel(_("Období:")))
        buttons.addWidget(self._flex_period)
        buttons.addSpacing(16)
        buttons.addWidget(add_btn)
        buttons.addWidget(self._undo_btn)
        buttons.addStretch()
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(buttons)
        layout.addWidget(QLabel(_("Historie importů")))
        layout.addWidget(self._table, 1)
        layout.addWidget(QLabel(_("Výsledek posledního importu")))
        layout.addWidget(self._log)
        self.refresh()

    def refresh(self) -> None:
        self._model.set_rows(queries.list_batches(self._engine))
        self._fill_flex_periods()
        self.refresh_sources()

    def refresh_sources(self) -> None:
        self._sources = load_sources(self._engine)
        selected = self._source.currentData()
        self._source.clear()
        active = [s for s in self._sources if s.enabled]
        self._source.addItem(_("Všechny ({count})").format(count=len(active)), SOURCES_ALL_KEY)
        for s in active:
            self._source.addItem(s.name, s.id)
        self._source.setCurrentIndex(max(self._source.findData(selected), 0))
        self._sync_btn.setEnabled(bool(self._sources) or self._worker is not None)

    def _fill_flex_periods(self) -> None:
        current = date.today().year
        data_years = queries.available_years(self._engine)
        oldest = min([*data_years, current - FLEX_YEARS_OFFERED + 1])
        # Keep the user's choice across refreshes; the first fill selects the current year
        had_items = self._flex_period.count() > 0
        selected = self._flex_period.currentData()
        self._flex_period.clear()
        self._flex_period.addItem(_("Letošní rok ({year})").format(year=current), f"{current}-{current}")
        for year in range(current - 1, oldest - 1, -1):
            self._flex_period.addItem(str(year), f"{year}-{year}")
        first = min(data_years, default=current - 1)
        if first < current:
            self._flex_period.addItem(
                _("Všechny roky {first}–{last}").format(first=first, last=current), f"{first}-{current}"
            )
        self._flex_period.addItem(_("Podle nastavení Flex Query"), QUERY_PERIOD_KEY)
        index = self._flex_period.findData(selected) if had_items else 0
        self._flex_period.setCurrentIndex(max(index, 0))

    def import_paths(self, paths: list[Path]) -> None:
        self._log.clear()
        for path in paths:
            try:
                res = import_service.import_file(self._engine, path)
            except (ValueError, OSError) as exc:
                self._log.appendPlainText(_("CHYBA  {file}: {error}").format(file=path.name, error=exc))
                continue
            self._log.appendPlainText(
                _("OK     {file}: nové {new}, duplicitní {duplicate}").format(
                    file=res.file_name, new=res.total_new, duplicate=res.total_duplicate
                )
            )
            for w in res.warnings:
                self._log.appendPlainText(f"       ⚠ {w}")
        self.refresh()
        self.data_changed.emit()

    def _period(self) -> FlexPeriod:
        key = self._flex_period.currentData()
        if key == QUERY_PERIOD_KEY:
            return QUERY_PERIOD
        first, last = (int(y) for y in key.split("-"))
        return years_period(first, last)

    def _sync(self) -> None:
        key = self._source.currentData()
        sources = [s for s in self._sources if s.enabled and key in (SOURCES_ALL_KEY, s.id)]
        if not sources:
            QMessageBox.information(
                self,
                _("Zdroje dat"),
                _("Žádný zdroj dat – přidejte ho v záložce Nastavení → Zdroje dat."),
            )
            return
        try:
            period = self._period()
        except ValueError as exc:
            QMessageBox.information(self, _("Zdroje dat"), str(exc))
            return
        self._log.clear()
        worker = self._worker = SourcesWorker(sources, period, source_sync.known_hashes(self._engine))
        worker.progress.connect(self._log.appendPlainText)
        worker.finished.connect(self._sources_fetched)
        worker.cancelled.connect(self._sync_done)
        self._show_running(True)
        background.start(worker, "sources-update")

    def _sync_or_stop(self) -> None:
        if self._worker is None:
            self._sync()
            return
        # Stop: the window is free right away; the thread ends at its next step or request timeout
        # and whatever it still delivers is ignored.
        worker, self._worker = self._worker, None
        worker.cancel.set()
        for signal in (worker.progress, worker.finished, worker.cancelled):
            signal.disconnect()
        self._log.appendPlainText(
            "⏹ "
            + _("Zastaveno. Rozpracovaný požadavek se ukončí nejpozději za {seconds} s.").format(
                seconds=flex_web.HTTP_TIMEOUT
            )
        )
        self._show_running(False)

    def _show_running(self, running: bool) -> None:
        self._sync_btn.setText(_("Zastavit") if running else _("Aktualizovat ze zdrojů"))
        self._sync_btn.setProperty("primary", not running)
        self._sync_btn.style().unpolish(self._sync_btn)  # re-apply the stylesheet for the new property
        self._sync_btn.style().polish(self._sync_btn)
        self._sync_btn.setEnabled(True)
        for widget in (self._source, self._flex_period):
            widget.setEnabled(not running)

    def _sources_fetched(self, results: list[SourceResult]) -> None:
        self._sync_done()
        source_sync.import_all(self._engine, results)  # importing is quick (~0.5 s for a year of IBKR)
        self._log.appendPlainText("")
        for r in results:
            if r.error:
                self._log.appendPlainText(
                    _("CHYBA  {source}: {error}").format(source=r.source.name, error=r.error)
                )
                continue
            new = sum(res.total_new for res in r.imports)
            self._log.appendPlainText(
                _("OK     {source}: souborů {files}, nových záznamů {new}").format(
                    source=r.source.name, files=len(r.paths), new=new
                )
            )
            for res in r.imports:
                for w in res.warnings:
                    self._log.appendPlainText(f"       ⚠ {res.file_name}: {w}")
            for name, error in r.import_errors:
                self._log.appendPlainText(_("CHYBA  {file}: {error}").format(file=name, error=error))
        self.refresh()
        self.data_changed.emit()

    def _sync_done(self) -> None:
        self._worker = None
        self._show_running(False)

    def _choose_files(self) -> None:
        files, _filter = QFileDialog.getOpenFileNames(
            self,
            _("Vyberte exporty z IBKR nebo XTB"),
            "",
            _("Exporty IBKR a XTB (*.csv *.xml *.xlsx);;Vše (*)"),
        )
        if files:
            self.import_paths([Path(f) for f in files])

    def _selected_batches(self) -> list[BatchRow]:
        rows = sorted({i.row() for i in self._table.selectionModel().selectedRows()})
        return [self._model.row_at(r) for r in rows]

    def _selection_changed(self) -> None:
        count = len(self._selected_batches())
        self._undo_btn.setEnabled(count > 0)
        self._undo_btn.setText(
            _("Smazat vybrané importy ({count})").format(count=count)
            if count > 1
            else _("Smazat vybrané importy")
        )

    def _undo_selected(self) -> None:
        batches = self._selected_batches()
        if not batches:
            return
        if len(batches) == 1:
            question = _("Odstranit import #{id} ({file}) a všechny záznamy, které přinesl?").format(
                id=batches[0].id, file=batches[0].file_name
            )
        else:
            listing = "\n".join(f"#{b.id}  {b.file_name}" for b in batches[:MAX_LISTED])
            if len(batches) > MAX_LISTED:
                listing += "\n" + _("… a dalších {count}").format(count=len(batches) - MAX_LISTED)
            question = (
                _("Odstranit {count} importů a všechny záznamy, které přinesly?").format(count=len(batches))
                + "\n\n"
                + listing
            )
        answer = QMessageBox.question(self, _("Smazat importy"), question)
        if answer == QMessageBox.StandardButton.Yes:
            import_service.undo_imports(self._engine, [b.id for b in batches])
            self.refresh()
            self._selection_changed()
            self.data_changed.emit()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.import_paths(paths)

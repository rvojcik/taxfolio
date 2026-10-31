"""Main window: global scope selectors (account, year) and the module tabs."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QComboBox, QLabel, QMainWindow, QTabWidget, QToolBar
from sqlalchemy import Engine

from taxfolio import __version__
from taxfolio.i18n import _
from taxfolio.services import queries, updates
from taxfolio.services.settings import load_settings
from taxfolio.ui import background, theme
from taxfolio.ui.import_view import ImportView
from taxfolio.ui.journal_view import JournalView
from taxfolio.ui.notices import Level, Notice
from taxfolio.ui.overview_view import OverviewView
from taxfolio.ui.realized_view import RealizedView
from taxfolio.ui.settings_view import SettingsView
from taxfolio.ui.simulator_view import SimulatorView
from taxfolio.ui.tax_view import TaxView

# After a failed rate download (network problem) try again this much later
RATES_RETRY_MS = 5 * 60_000


class MainWindow(QMainWindow):
    # The settings switched the language or the appearance; the application rebuilds the window
    rebuild_requested = Signal()

    def __init__(self, engine: Engine, background_rates: bool = False) -> None:
        """``background_rates``: download exchange rates in a background thread (the desktop app;
        reports then use only stored rates and never wait on the network)."""
        super().__init__()
        self._engine = engine
        self._background_rates = background_rates
        self._rates_worker: background.RatesWorker | None = None
        self._rates_retry = QTimer(self)
        self._rates_retry.setSingleShot(True)
        self._rates_retry.timeout.connect(self.refresh_rates)
        self._update_worker: background.UpdateWorker | None = None
        # Coloured notices on the left; "new version available" badge on the right until the window closes
        self._notice = Notice()
        self.statusBar().addWidget(self._notice)
        self._update_link = QLabel()
        self._update_link.setObjectName("updateNotice")
        self._update_link.setOpenExternalLinks(True)
        self._update_link.hide()
        self.statusBar().addPermanentWidget(self._update_link)
        self.setWindowTitle(_("Taxfolio"))
        self.resize(1400, 820)

        self._account = QComboBox()
        self._year = QComboBox()
        toolbar = QToolBar("Rozsah")
        toolbar.setMovable(False)
        toolbar.addWidget(QLabel(_(" Účet: ")))
        toolbar.addWidget(self._account)
        toolbar.addWidget(QLabel(_("  Rok: ")))
        toolbar.addWidget(self._year)
        self.addToolBar(toolbar)

        self._import = ImportView(engine)
        self._overview = OverviewView(engine)
        self._journal = JournalView(engine)
        self._realized = RealizedView(engine)
        self._tax = TaxView(engine)
        self._simulator = SimulatorView(engine)
        self._settings = SettingsView(engine)
        tabs = self._tabs = QTabWidget()
        tabs.addTab(self._overview, _("Přehled"))
        tabs.addTab(self._journal, _("Obchodní deník"))
        tabs.addTab(self._realized, _("Realizace (FIFO)"))
        tabs.addTab(self._tax, _("Daně"))
        tabs.addTab(self._simulator, _("Simulace prodeje"))
        tabs.addTab(self._import, _("Import"))
        tabs.addTab(self._settings, _("Nastavení"))
        self.setCentralWidget(tabs)

        self._import.data_changed.connect(self._reload_scope)
        self._import.data_changed.connect(self._settings.refresh)  # new currencies may appear
        self._settings.settings_changed.connect(self._settings_changed)
        self._settings.sources.sources_changed.connect(self._import.refresh_sources)
        self._settings.rebuild_requested.connect(self.rebuild_requested.emit)
        self._settings.rates_requested.connect(self.refresh_rates)
        self._import.notice.connect(lambda text, level, busy: self.notify(text, Level(level), busy=busy))
        self._settings.update_check_requested.connect(lambda: self.check_for_update(manual=True))
        self._import.data_changed.connect(self.refresh_rates)  # imported years may lack rates
        self._account.currentIndexChanged.connect(self._scope_changed)
        self._year.currentIndexChanged.connect(self._scope_changed)
        self._reload_scope()
        if not queries.list_batches(engine):
            tabs.setCurrentWidget(self._import)
        if background_rates:
            # after the window is shown; the context object cancels them if the window goes away first
            QTimer.singleShot(0, self, self.refresh_rates)
            if load_settings(engine).check_updates and updates.check_due(engine):
                QTimer.singleShot(0, self, self.check_for_update)

    def _reload_scope(self) -> None:
        account, year = self._account.currentData(), self._year.currentData()
        for combo in (self._account, self._year):
            combo.blockSignals(True)
            combo.clear()
        self._account.addItem(_("Všechny účty"), None)
        for acc_id, _name, base in queries.list_accounts(self._engine):
            self._account.addItem(f"{acc_id} ({base})", acc_id)
        self._year.addItem(_("Všechny roky"), None)
        for y in queries.available_years(self._engine):
            self._year.addItem(str(y), y)
        for combo, value in ((self._account, account), (self._year, year)):
            idx = combo.findData(value)
            combo.setCurrentIndex(max(idx, 0))
            combo.blockSignals(False)
        self._scope_changed()

    def _scope_changed(self) -> None:
        self._overview.set_scope(self._account.currentData(), self._year.currentData())
        self._journal.set_scope(self._account.currentData(), self._year.currentData())
        self._realized.set_scope(self._account.currentData(), self._year.currentData())
        self._tax.set_scope(self._account.currentData(), self._year.currentData())
        self._simulator.set_scope(self._account.currentData(), self._year.currentData())

    def refresh_rates(self) -> None:
        """Download missing ČNB / ECB rates off the UI thread, then recompute the views."""
        if not self._background_rates or self._rates_worker is not None:
            return
        self._rates_retry.stop()
        years = {*queries.available_years(self._engine), date.today().year}
        worker = self._rates_worker = background.RatesWorker(self._engine, years)
        worker.finished.connect(self._rates_ready)
        worker.failed.connect(self._rates_failed)
        self.notify(_("Stahuji kurzy ČNB a ECB…"), Level.INFO, busy=True)
        background.start(worker, "rates")

    def _rates_ready(self, fetched: list[str]) -> None:
        self._rates_worker = None
        if fetched:
            self.notify(_("Staženy kurzy: {sources}").format(sources=", ".join(fetched)), Level.SUCCESS)
            self._scope_changed()
            self._settings.refresh()
        else:
            self.notify(_("Kurzy jsou aktuální."), Level.SUCCESS, timeout=5_000)

    def _rates_failed(self, error: str) -> None:
        self._rates_worker = None
        minutes = RATES_RETRY_MS // 60_000
        self.notify(
            _(
                "Kurzy se nepodařilo stáhnout ({error}); používají se uložené. Další pokus za {minutes} min."
            ).format(error=error, minutes=minutes),
            Level.WARNING,
        )
        self._rates_retry.start(RATES_RETRY_MS)

    def check_for_update(self, manual: bool = False) -> None:
        """Ask GitHub for a newer release in the background; ``manual`` also reports 'up to date'."""
        if self._update_worker is not None:
            return
        worker = self._update_worker = background.UpdateWorker()
        worker.finished.connect(lambda release: self._update_checked(release, manual))
        worker.failed.connect(lambda error: self._update_failed(error, manual))
        if manual:
            self.notify(_("Hledám novou verzi…"), Level.INFO, busy=True)
        background.start(worker, "update-check")

    def _update_checked(self, release: updates.Release | None, manual: bool) -> None:
        self._update_worker = None
        updates.mark_checked(self._engine)
        if release is None:
            if manual:
                self.notify(
                    _("Používáte nejnovější verzi {version}.").format(version=__version__), Level.SUCCESS
                )
            return
        # The link takes the badge's text colour (a link would be accent on accent otherwise)
        self._update_link.setText(
            '<a href="{url}" style="color: {color}; text-decoration: none;">⬆  {text}</a>'.format(
                url=release.url,
                color=theme.current().accent_ink,
                text=_("Je k dispozici nová verze {version} – stáhnout").format(version=release.version),
            )
        )
        self._update_link.setToolTip(release.url)
        self._update_link.show()

    def _update_failed(self, error: str, manual: bool) -> None:
        self._update_worker = None
        if manual:  # an automatic check stays quiet and tries again next start
            self.notify(_("Novou verzi se nepodařilo zjistit: {error}").format(error=error), Level.WARNING)

    def notify(
        self, text: str, level: Level = Level.INFO, timeout: int | None = -1, busy: bool = False
    ) -> None:
        """Coloured notice in the status bar (see ui/notices.py)."""
        self._notice.show_notice(text, level, timeout, busy)

    def current_tab_index(self) -> int:
        return self._tabs.currentIndex()

    def set_current_tab_index(self, index: int) -> None:
        self._tabs.setCurrentIndex(index)

    def _settings_changed(self) -> None:
        self._tax.apply_settings()
        self._scope_changed()

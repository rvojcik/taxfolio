"""Desktop application entry point."""

from __future__ import annotations

import signal
import sys
from importlib import resources

from PySide6.QtCore import QByteArray, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication
from sqlalchemy import Engine

from taxfolio.i18n import set_language, system_language
from taxfolio.services import rates_service
from taxfolio.services.settings import load_settings
from taxfolio.storage.db import open_db
from taxfolio.ui import theme
from taxfolio.ui.main_window import MainWindow


def apply_language(engine: Engine) -> None:
    """Use the language from the settings, or the operating system's when none is chosen."""
    set_language(load_settings(engine).language or system_language())


def apply_appearance(engine: Engine) -> None:
    app = QApplication.instance()
    if isinstance(app, QApplication):
        theme.apply(app, load_settings(engine).appearance)


class Application:
    """Owns the main window and rebuilds it when the user switches the language or the appearance."""

    def __init__(self, engine: Engine, background_rates: bool = False) -> None:
        self._engine = engine
        self._background_rates = background_rates
        self.window: MainWindow | None = None
        self.show_window()

    def show_window(self, geometry: object = None) -> None:
        apply_language(self._engine)
        apply_appearance(self._engine)
        window = MainWindow(self._engine, self._background_rates)
        window.rebuild_requested.connect(self._rebuild)
        if geometry is not None:
            window.restoreGeometry(geometry)  # type: ignore[arg-type]
        window.show()
        self.window = window

    def _rebuild(self) -> None:
        old = self.window
        assert old is not None
        geometry, tab = old.saveGeometry(), old.current_tab_index()
        self.show_window(geometry)
        assert self.window is not None
        self.window.set_current_tab_index(tab)
        old.close()
        old.deleteLater()


# How often the Qt event loop hands control back to Python so it can run signal handlers
SIGNAL_POLL_MS = 200


def quit_on_signals(app: QApplication) -> QTimer:
    """Close the app on Ctrl+C (SIGINT) or SIGTERM from the console.

    Python runs signal handlers only between bytecodes, and Qt's event loop runs in C++, so a
    signal would wait until the next mouse move. A no-op timer lets Python check regularly.
    """

    def stop(signum: int, _frame: object) -> None:
        app.closeAllWindows()
        app.exit(128 + signum)  # the shell convention for "terminated by a signal"

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)
    timer = QTimer(app)
    timer.timeout.connect(lambda: None)
    timer.start(SIGNAL_POLL_MS)
    return timer


def app_icon() -> QIcon:
    svg = resources.files("taxfolio.resources").joinpath("taxfolio.svg").read_bytes()
    pixmap = QPixmap()
    pixmap.loadFromData(QByteArray(svg), "SVG")
    return QIcon(pixmap)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("taxfolio")
    # Matches taxfolio.desktop, so the window groups under the launcher icon (Wayland app id)
    app.setDesktopFileName("taxfolio")
    app.setWindowIcon(app_icon())
    quit_on_signals(app)
    # Exchange rates download in a background thread; reports use the stored ones (never block)
    rates_service.set_auto_download(False)
    _application = Application(open_db(), background_rates=True)  # keep a reference for the event loop
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

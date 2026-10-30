"""Work that may wait on the network runs off the UI thread, so the window always responds.

Workers are QObjects living in the UI thread; their ``run`` executes in a daemon thread and the
signals it emits are queued back to the UI thread. Daemon threads never keep the application from
quitting, even when a request is still waiting for its timeout.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from urllib.error import URLError

from PySide6.QtCore import QObject, Signal
from sqlalchemy import Engine

from taxfolio.services import rates_service, updates


def start(worker: QObject, name: str) -> threading.Thread:
    """Run ``worker.run()`` in a daemon thread (the caller keeps a reference to the worker)."""

    def run() -> None:
        try:
            worker.run()  # type: ignore[attr-defined]
        except RuntimeError:  # the window owning the worker was closed meanwhile – nobody listens
            pass

    thread = threading.Thread(target=run, name=name, daemon=True)
    thread.start()
    return thread


class RatesWorker(QObject):
    """Downloads missing ČNB / ECB rates into the database."""

    finished = Signal(list)  # notes on what was fetched (empty = already up to date)
    failed = Signal(str)

    def __init__(self, engine: Engine, years: Iterable[int]) -> None:
        super().__init__()
        self._engine, self._years = engine, set(years)

    def run(self) -> None:
        try:
            notes = rates_service.download_rates(self._engine, self._years)
        except (URLError, OSError, ValueError) as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(notes)


class UpdateWorker(QObject):
    """Asks GitHub for the latest release."""

    finished = Signal(object)  # updates.Release when newer than the running version, else None
    failed = Signal(str)

    def run(self) -> None:
        try:
            release = updates.newer_release()
        except (URLError, OSError, ValueError, KeyError) as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(release)

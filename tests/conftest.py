from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine

from taxfolio.storage.db import open_db

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return open_db(tmp_path / "test.sqlite")


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never download rates; flat rates are served instead."""
    from datetime import date, timedelta
    from decimal import Decimal

    from taxfolio.fx import sources
    from taxfolio.fx.sources import CNB, ECB, RateRow

    # Consistent cross rates: 1 USD = 22 CZK, 1 EUR = 1.1 USD = 24.2 CZK
    def flat(source: str, rates: dict[str, str], years: set[int]) -> list[RateRow]:
        out = []
        for y in years:
            d = date(y, 1, 1)
            while d.year == y:
                out.extend(RateRow(source, ccy, d, Decimal(rate)) for ccy, rate in rates.items())
                d += timedelta(days=1)
        return out

    monkeypatch.setattr(
        sources, "fetch_cnb_year", lambda year: flat(CNB, {"USD": "22", "EUR": "24.2"}, {year})
    )
    monkeypatch.setattr(
        sources, "fetch_ecb", lambda years: flat(ECB, {"USD": "1.1", "CZK": "24.2"}, set(years))
    )


@pytest.fixture(autouse=True)
def memory_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never touch the real OS keychain from tests."""
    import keyring
    from keyring.backend import KeyringBackend
    from keyring.errors import PasswordDeleteError

    class MemoryKeyring(KeyringBackend):
        priority = 1  # type: ignore[assignment]

        def __init__(self) -> None:
            super().__init__()
            self.store: dict[tuple[str, str], str] = {}

        def get_password(self, service: str, username: str) -> str | None:
            return self.store.get((service, username))

        def set_password(self, service: str, username: str, password: str) -> None:
            self.store[(service, username)] = password

        def delete_password(self, service: str, username: str) -> None:
            if self.store.pop((service, username), None) is None:
                raise PasswordDeleteError("not found")

    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    monkeypatch.delenv("IBKR_FLEX_TOKEN", raising=False)
    yield
    keyring.set_keyring(previous)


@pytest.fixture(autouse=True)
def delete_windows() -> Iterator[None]:
    """Qt widgets of a finished test must not linger: every later style change would repolish them."""
    yield
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

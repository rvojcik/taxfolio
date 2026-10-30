import json
import urllib.error
from datetime import datetime, timedelta

import pytest
from sqlalchemy import Engine

from taxfolio.services import updates
from taxfolio.services.settings import AppSettings, load_settings, save_settings


def github(tag: str):  # noqa: ANN201
    body = json.dumps(
        {"tag_name": tag, "html_url": f"https://github.com/x/y/releases/tag/{tag}", "name": tag}
    )
    return lambda _url: body.encode()


@pytest.mark.parametrize(
    ("latest", "current", "newer"),
    [
        ("v0.2.0", "0.1.0", True),
        ("v0.10.0", "0.9.3", True),
        ("v0.1.0", "0.1.0", False),
        ("v1.0.0", "1.0.1", False),
    ],
)
def test_version_comparison(latest: str, current: str, newer: bool) -> None:
    release = updates.newer_release(current, get=github(latest))
    assert (release is not None) == newer
    if release:
        assert release.version == latest.lstrip("v") and release.url.endswith(latest)


def test_no_release_yet_is_not_an_error() -> None:
    def not_found(url: str) -> bytes:
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]

    assert updates.newer_release("0.1.0", get=not_found) is None


def test_check_at_most_once_a_day(engine: Engine) -> None:
    now = datetime(2026, 10, 30, 12, 0)
    assert updates.check_due(engine, now)
    updates.mark_checked(engine, now)
    assert not updates.check_due(engine, now + timedelta(hours=23))
    assert updates.check_due(engine, now + timedelta(days=1))
    # saving the settings must not reset the check (stored separately)
    save_settings(engine, AppSettings(check_updates=False))
    assert not updates.check_due(engine, now + timedelta(hours=1))
    assert load_settings(engine).check_updates is False


def test_window_shows_link_to_new_release(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from taxfolio.ui import background
    from taxfolio.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(updates, "_http_get", github("v9.0.0"))
    started: list[object] = []
    monkeypatch.setattr(background, "start", lambda worker, name: started.append(worker))
    w = MainWindow(engine)
    w.check_for_update()
    (worker,) = started
    worker.run()  # type: ignore[attr-defined]
    app.processEvents()
    assert not w._update_link.isHidden() and "9.0.0" in w._update_link.text()
    assert not updates.check_due(engine)
    w.close()

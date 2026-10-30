"""Data of the old 'ibkr-tax' name move to 'taxfolio' once, nothing is lost."""

from pathlib import Path

import keyring

from taxfolio.services import secrets
from taxfolio.storage.db import DB_NAME, migrate_legacy_data_dir


def test_data_folder_moves_with_database_and_wal(tmp_path: Path) -> None:
    old, new = tmp_path / "ibkr-tax", tmp_path / "taxfolio"
    (old / "flex-downloads").mkdir(parents=True)
    (old / "ibkr-tax.sqlite").write_text("db")
    (old / "ibkr-tax.sqlite-wal").write_text("wal")
    (old / "flex-downloads" / "flex_1.xml").write_text("x")
    assert migrate_legacy_data_dir(old, new)
    assert not old.exists()
    assert (new / DB_NAME).read_text() == "db" and (new / f"{DB_NAME}-wal").read_text() == "wal"
    assert (new / "flex-downloads" / "flex_1.xml").exists()
    assert not migrate_legacy_data_dir(old, new)  # only once


def test_existing_new_folder_is_never_overwritten(tmp_path: Path) -> None:
    old, new = tmp_path / "ibkr-tax", tmp_path / "taxfolio"
    old.mkdir()
    (old / "ibkr-tax.sqlite").write_text("old")
    new.mkdir()
    (new / DB_NAME).write_text("new")
    assert not migrate_legacy_data_dir(old, new)
    assert (new / DB_NAME).read_text() == "new" and old.exists()


def test_tokens_move_from_the_old_keychain_service() -> None:
    keyring.set_password(secrets.LEGACY_SERVICE, "source:abc:token", "OLD")
    assert secrets.get_secret("abc", "token") == "OLD"
    assert keyring.get_password(secrets.SERVICE, "source:abc:token") == "OLD"
    assert keyring.get_password(secrets.LEGACY_SERVICE, "source:abc:token") is None


def test_new_launcher_removes_the_old_one(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from taxfolio import desktop

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    monkeypatch.setattr(desktop, "gui_command", lambda: "/opt/bin/taxfolio-gui")
    old = tmp_path / "applications" / "ibkr-tax.desktop"
    old.parent.mkdir(parents=True)
    old.write_text("[Desktop Entry]")
    entry, _icon = desktop.install()
    assert entry.name == "taxfolio.desktop" and not old.exists()

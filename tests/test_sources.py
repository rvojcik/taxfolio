import json
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.dialects.sqlite import insert

from taxfolio.services import secrets, source_sync
from taxfolio.services.flex_sync import QUERY_PERIOD
from taxfolio.services.sources import (
    InputSource,
    SourceType,
    load_sources,
    remove_source,
    save_sources,
)
from taxfolio.storage import schema


def test_save_and_load_keeps_secrets_out_of_the_database(engine: Engine) -> None:
    ibkr = InputSource(SourceType.IBKR_FLEX, "IBKR", {"query_id": "1", "token": "LEAK?"})
    folder = InputSource(SourceType.FOLDER, "XTB", {"path": "/tmp/x"}, enabled=False)
    save_sources(engine, [ibkr, folder])
    with engine.connect() as conn:
        stored = conn.execute(schema.app_setting.select()).mappings().all()
    assert "LEAK?" not in json.dumps([dict(r) for r in stored])
    loaded = load_sources(engine)
    assert [(s.name, s.type, s.enabled) for s in loaded] == [
        ("IBKR", SourceType.IBKR_FLEX, True),
        ("XTB", SourceType.FOLDER, False),
    ]
    assert loaded[1].value("pattern") == "*.csv *.xml *.xlsx"  # default of an empty optional field
    assert [f.key for f in loaded[0].missing()] == ["token"]
    secrets.set_secret(ibkr.id, "token", "T")
    assert loaded[0].missing() == []
    remove_source(engine, ibkr.id)
    assert [s.name for s in load_sources(engine)] == ["XTB"]
    assert secrets.get_secret(ibkr.id, "token") is None  # removing a source forgets its token


def test_env_token_serves_ibkr_sources(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    source = InputSource(SourceType.IBKR_FLEX, "IBKR", {"query_id": "1"})
    monkeypatch.setenv(secrets.ENV_VAR, "ENV")
    assert source.secret("token") == "ENV" and source.missing() == []


def test_legacy_flex_settings_become_the_first_source(engine: Engine) -> None:
    import keyring

    keyring.set_password(secrets.SERVICE, secrets.LEGACY_USERNAME, "OLD")
    with engine.begin() as conn:
        conn.execute(insert(schema.app_setting).values(key="flex_query_id", value=json.dumps("777")))
    (source,) = load_sources(engine)
    assert source.type is SourceType.IBKR_FLEX and source.value("query_id") == "777"
    assert secrets.get_secret(source.id, "token") == "OLD"
    assert secrets.get_legacy_token() is None
    assert [s.id for s in load_sources(engine)] == [source.id]  # migrated once, then stored


def test_folder_source_imports_only_new_files(engine: Engine, fixtures: Path, tmp_path: Path) -> None:
    folder = tmp_path / "exports"
    folder.mkdir()
    (folder / "a.xml").write_bytes((fixtures / "flex_2025.xml").read_bytes())
    (folder / "notes.txt").write_text("ignored")
    source = InputSource(SourceType.FOLDER, "Složka", {"path": str(folder)})
    (first,) = source_sync.sync_all(engine, [source])
    assert first.error == "" and [p.name for p in first.paths] == ["a.xml"]
    assert first.imports[0].total_new > 0
    (second,) = source_sync.sync_all(engine, [source])
    assert second.paths == []  # already imported (same content)


def test_one_failing_source_does_not_stop_the_others(engine: Engine, fixtures: Path, tmp_path: Path) -> None:
    broken = InputSource(SourceType.FOLDER, "Chybí", {"path": str(tmp_path / "nope")})
    no_token = InputSource(SourceType.IBKR_FLEX, "Bez tokenu", {"query_id": "1"})
    good_dir = tmp_path / "ok"
    good_dir.mkdir()
    (good_dir / "f.xml").write_bytes((fixtures / "flex_2025.xml").read_bytes())
    good = InputSource(SourceType.FOLDER, "OK", {"path": str(good_dir)})
    disabled = InputSource(SourceType.FOLDER, "Vypnuto", {"path": str(good_dir)}, enabled=False)
    results = source_sync.sync_all(engine, [broken, no_token, good, disabled], QUERY_PERIOD)
    by_name = {r.source.name: r for r in results}
    assert set(by_name) == {"Chybí", "Bez tokenu", "OK"}
    assert "neexistuje" in by_name["Chybí"].error and "Token" in by_name["Bez tokenu"].error
    assert by_name["OK"].imports and not by_name["OK"].error

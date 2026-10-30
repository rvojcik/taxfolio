"""Database location and engine setup."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from platformdirs import user_data_dir
from sqlalchemy import Engine, create_engine, event, select

from taxfolio.storage import schema

APP_NAME = "taxfolio"
DB_NAME = "taxfolio.sqlite"
# Before the project was renamed to Taxfolio (versions up to 0.1.0)
LEGACY_APP_NAME = "ibkr-tax"
LEGACY_DB_NAME = "ibkr-tax.sqlite"


def data_dir() -> Path:
    return Path(user_data_dir(APP_NAME, appauthor=False))


def default_db_path() -> Path:
    return data_dir() / DB_NAME


def migrate_legacy_data_dir(old: Path | None = None, new: Path | None = None) -> bool:
    """Move the data of the old 'ibkr-tax' name (database, downloaded statements) once.

    Runs only while the new folder does not exist yet; SQLite's -wal / -shm files move with the
    database so nothing written but not yet checkpointed is lost.
    """
    old = old or Path(user_data_dir(LEGACY_APP_NAME, appauthor=False))
    new = new or data_dir()
    if not old.is_dir() or new.exists():
        return False
    new.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old), str(new))
    for legacy in new.glob(LEGACY_DB_NAME + "*"):  # ibkr-tax.sqlite, -wal, -shm
        legacy.rename(new / (DB_NAME + legacy.name[len(LEGACY_DB_NAME) :]))
    return True


def open_db(path: Path | None = None) -> Engine:
    """Open (and create if needed) the database. ``path=None`` uses the per-user data dir."""
    if path is None:
        migrate_legacy_data_dir()
        path = default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    schema.metadata.create_all(engine)
    with engine.begin() as conn:
        version = conn.execute(
            select(schema.meta.c.value).where(schema.meta.c.key == "schema_version")
        ).scalar_one_or_none()
        if version is None:
            conn.execute(schema.meta.insert().values(key="schema_version", value=str(schema.SCHEMA_VERSION)))
        elif int(version) < schema.SCHEMA_VERSION:
            # Pre-release: imported data is reproducible from the source files and there are no user
            # annotations yet, so an outdated schema is simply rebuilt. Alembic replaces this once
            # annotations exist (ARCHITEKTURA.md §9).
            print(
                f"Schéma databáze {version} → {schema.SCHEMA_VERSION}: databáze se znovu zakládá, "
                "importujte soubory znovu.",
                file=sys.stderr,
            )
            schema.metadata.drop_all(conn)
            schema.metadata.create_all(conn)
            conn.execute(schema.meta.insert().values(key="schema_version", value=str(schema.SCHEMA_VERSION)))
        elif int(version) > schema.SCHEMA_VERSION:
            raise RuntimeError(
                f"Databáze má novější schéma ({version}) než aplikace ({schema.SCHEMA_VERSION})."
            )
    return engine

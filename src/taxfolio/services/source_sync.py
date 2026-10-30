"""Update data from all input sources: download (worker thread) and import (UI thread).

``fetch_all`` touches no database, so it can run off the UI thread; it gets the hashes of the
already imported files up front. ``import_all`` then imports the collected files.
"""

from __future__ import annotations

import functools
import hashlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine, select

from taxfolio.i18n import _
from taxfolio.importers import flex_web
from taxfolio.services import flex_sync, import_service
from taxfolio.services.flex_sync import QUERY_PERIOD, FlexPeriod
from taxfolio.services.import_service import ImportResult
from taxfolio.services.secrets import SecretStoreError
from taxfolio.services.sources import InputSource, SourceType
from taxfolio.storage import schema

Progress = Callable[[str], None]


class Cancelled(Exception):
    """The user stopped the update."""


def _cancellable(cancel: threading.Event) -> tuple[Callable[[float], None], Callable[[str], bytes]]:
    """A sleep and an HTTP get that give up as soon as ``cancel`` is set."""

    def sleep(seconds: float) -> None:
        if cancel.wait(seconds):
            raise Cancelled

    def get(url: str) -> bytes:
        if cancel.is_set():
            raise Cancelled
        data = flex_web.http_get(url)
        if cancel.is_set():  # the answer came after Stop: do not use it
            raise Cancelled
        return data

    return sleep, get


@dataclass
class SourceResult:
    source: InputSource
    paths: list[Path] = field(default_factory=list)
    error: str = ""
    imports: list[ImportResult] = field(default_factory=list)
    import_errors: list[tuple[str, str]] = field(default_factory=list)  # (file, error)


def known_hashes(engine: Engine) -> set[str]:
    b = schema.import_batch
    with engine.connect() as conn:
        return {h for (h,) in conn.execute(select(b.c.file_sha256))}


def folder_files(source: InputSource, known: set[str]) -> list[Path]:
    """Files in the source folder matching its patterns that were not imported yet."""
    folder = Path(source.value("path")).expanduser()
    if not folder.is_dir():
        raise FileNotFoundError(_("Složka {path} neexistuje.").format(path=folder))
    patterns = source.value("pattern").replace(";", " ").replace(",", " ").split()
    files = sorted({p for pattern in patterns for p in folder.glob(pattern) if p.is_file()})
    return [p for p in files if hashlib.sha256(p.read_bytes()).hexdigest() not in known]


def fetch_source(
    source: InputSource,
    period: FlexPeriod,
    known: set[str],
    progress: Progress = lambda _msg: None,
    fetch: Callable[..., bytes] = flex_web.fetch_statement,
    cancel: threading.Event | None = None,
) -> SourceResult:
    result = SourceResult(source)
    pause: Callable[[float], None] = time.sleep
    if cancel is not None:
        pause, get = _cancellable(cancel)
        if fetch is flex_web.fetch_statement:
            fetch = functools.partial(fetch, sleep=pause, get=get)
    try:
        if missing := source.missing():
            raise ValueError(
                _("chybí {fields} – doplňte v Nastavení → Zdroje dat").format(
                    fields=", ".join(_(f.label) for f in missing)
                )
            )
        if source.type is SourceType.IBKR_FLEX:
            token = source.secret("token") or ""
            result.paths = flex_sync.download_statements(
                token, source.value("query_id"), period, progress=progress, fetch=fetch, sleep=pause
            )
        elif source.type is SourceType.FOLDER:
            result.paths = folder_files(source, known)
            progress(_("Nových souborů: {count}").format(count=len(result.paths)))
    except (flex_web.FlexWebError, SecretStoreError, OSError, ValueError) as exc:
        result.error = str(exc)
    return result


def fetch_all(
    sources: list[InputSource],
    period: FlexPeriod = QUERY_PERIOD,
    known: set[str] | None = None,
    progress: Progress = lambda _msg: None,
    fetch: Callable[..., bytes] = flex_web.fetch_statement,
    sleep: Callable[[float], None] = time.sleep,
    cancel: threading.Event | None = None,
) -> list[SourceResult]:
    """Download from every enabled source; one failing source does not stop the others.

    ``cancel`` stops the run: waiting and the next request raise ``Cancelled``. A request already
    sent ends by its timeout (flex_web.HTTP_TIMEOUT) and its answer is thrown away.
    """
    if cancel is not None:
        sleep, _get = _cancellable(cancel)
    results = []
    active = [s for s in sources if s.enabled]
    for i, source in enumerate(active):
        if cancel is not None and cancel.is_set():
            raise Cancelled
        if i and source.type is SourceType.IBKR_FLEX:
            sleep(flex_sync.PAUSE_BETWEEN_REQUESTS)  # IBKR rate limit across sources too
        progress(f"▶ {source.name} ({_(source.spec.title)})")
        # errors are reported once, in the summary after the import (UI log, CLI)
        results.append(fetch_source(source, period, known or set(), progress, fetch, cancel))
    return results


def import_all(engine: Engine, results: list[SourceResult]) -> list[SourceResult]:
    for result in results:
        for path in result.paths:
            try:
                result.imports.append(import_service.import_file(engine, path))
            except (ValueError, OSError) as exc:
                result.import_errors.append((path.name, str(exc)))
    return results


def sync_all(
    engine: Engine,
    sources: list[InputSource],
    period: FlexPeriod = QUERY_PERIOD,
    progress: Progress = lambda _msg: None,
    fetch: Callable[..., bytes] = flex_web.fetch_statement,
) -> list[SourceResult]:
    """Download and import in one go (CLI)."""
    return import_all(engine, fetch_all(sources, period, known_hashes(engine), progress, fetch))

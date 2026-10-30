"""Download Flex statements and import them (the 'Stáhnout z IBKR' action)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from platformdirs import user_data_dir
from sqlalchemy import Engine

from taxfolio.i18n import _
from taxfolio.importers import flex_web
from taxfolio.services import import_service
from taxfolio.services.import_service import ImportResult
from taxfolio.storage.db import APP_NAME

# Pause between two statements: IBKR allows 1 request per second and 10 per minute
PAUSE_BETWEEN_REQUESTS = 2.0

DateRange = tuple[date, date]


@dataclass(frozen=True)
class FlexPeriod:
    """What to download: a date range, or ``None`` dates for the period saved in the Flex Query."""

    start: date | None = None
    end: date | None = None

    def ranges(self) -> list[DateRange | None]:
        """Requests to send: one per calendar year, a full leap year (366 days) in two halves."""
        if self.start is None or self.end is None:
            return [None]
        out: list[DateRange | None] = []
        for year in range(self.start.year, self.end.year + 1):
            first, last = max(self.start, date(year, 1, 1)), min(self.end, date(year, 12, 31))
            if (last - first).days + 1 > flex_web.MAX_RANGE_DAYS:
                out += [(first, date(year, 6, 30)), (date(year, 7, 1), last)]
            else:
                out.append((first, last))
        return out


# The period saved in the Flex Query itself (no fd/td in the request)
QUERY_PERIOD = FlexPeriod()


def last_available_day(today: date | None = None) -> date:
    """IBKR statements reach the previous day at most."""
    return (today or date.today()) - timedelta(days=1)


def years_period(first: int, last: int, today: date | None = None) -> FlexPeriod:
    """Calendar years ``first``..``last``; the current year ends yesterday."""
    end = min(date(last, 12, 31), last_available_day(today))
    start = date(first, 1, 1)
    if end < start:
        raise ValueError(_("Za rok {year} zatím IBKR nemá žádná data.").format(year=first))
    return FlexPeriod(start, end)


def downloads_dir() -> Path:
    """Downloaded statements are kept next to the database (audit trail, re-import)."""
    return Path(user_data_dir(APP_NAME, appauthor=False)) / "flex-downloads"


def download_statement(
    token: str,
    query_id: str,
    dest_dir: Path | None = None,
    progress: Callable[[str], None] = lambda _msg: None,
    fetch: Callable[..., bytes] = flex_web.fetch_statement,
    date_range: DateRange | None = None,
) -> Path:
    """Fetch one statement and save it; safe to run in a worker thread (no database access)."""
    if date_range is None:
        data = fetch(token, query_id, progress=progress)
        suffix = ""
    else:
        start, end = date_range
        progress(_("Období {start} – {end}").format(start=f"{start:%d.%m.%Y}", end=f"{end:%d.%m.%Y}"))
        data = fetch(token, query_id, progress=progress, from_date=start, to_date=end)
        suffix = f"_{start:%Y%m%d}-{end:%Y%m%d}"
    stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
    target = (dest_dir or downloads_dir()) / f"flex_{query_id}{suffix}_{stamp}.xml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    progress(_("Uloženo do {path}").format(path=target))
    return target


def download_statements(
    token: str,
    query_id: str,
    period: FlexPeriod = QUERY_PERIOD,
    dest_dir: Path | None = None,
    progress: Callable[[str], None] = lambda _msg: None,
    fetch: Callable[..., bytes] = flex_web.fetch_statement,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Path]:
    """All statements of ``period``, one request per piece; no database access."""
    paths = []
    for i, date_range in enumerate(period.ranges()):
        if i:
            sleep(PAUSE_BETWEEN_REQUESTS)
        paths.append(download_statement(token, query_id, dest_dir, progress, fetch, date_range))
    return paths


def sync(
    engine: Engine,
    token: str,
    query_id: str,
    dest_dir: Path | None = None,
    progress: Callable[[str], None] = lambda _msg: None,
    fetch: Callable[..., bytes] = flex_web.fetch_statement,
    period: FlexPeriod = QUERY_PERIOD,
) -> list[ImportResult]:
    paths = download_statements(token, query_id, period, dest_dir, progress, fetch)
    return [import_service.import_file(engine, path) for path in paths]

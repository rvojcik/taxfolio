"""Check GitHub for a newer release of the application.

Asks the public GitHub API for the latest (non-draft, non-prerelease) release of the repository;
sends nothing but a plain GET with the app's user agent. The desktop app checks at most once a day
(CHECK_INTERVAL) in a background thread and can be switched off in the settings.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Engine, select
from sqlalchemy.dialects.sqlite import insert

from taxfolio import __version__
from taxfolio.storage import schema

REPOSITORY = "rvojcik/taxfolio"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases"
CHECK_INTERVAL = timedelta(days=1)
TIMEOUT = 10  # seconds; the check must never hold anything up
_STATE_KEY = "update_check"  # app_setting: when we last asked GitHub

HttpGet = Callable[[str], bytes]


@dataclass(frozen=True)
class Release:
    version: str  # "1.2.0" (tag without the leading v)
    url: str  # release page with the installers
    name: str = ""

    def is_newer_than(self, current: str) -> bool:
        return parse_version(self.version) > parse_version(current)


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.10.2' → (1, 10, 2); anything after the numbers (e.g. '-rc1') is ignored."""
    numbers = re.match(r"v?(\d+(?:\.\d+)*)", text.strip())
    return tuple(int(n) for n in numbers.group(1).split(".")) if numbers else (0,)


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"taxfolio/{__version__}", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 – fixed https URL
        data: bytes = resp.read()
        return data


def latest_release(get: HttpGet | None = None) -> Release | None:
    """The latest published release; None while the repository has none (GitHub answers 404)."""
    try:
        body = (get or _http_get)(LATEST_RELEASE_API)  # resolved at call time (tests replace it)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    data = json.loads(body)
    tag = str(data["tag_name"])
    return Release(tag.lstrip("v"), str(data.get("html_url") or RELEASES_PAGE), str(data.get("name") or tag))


def newer_release(current: str = __version__, get: HttpGet | None = None) -> Release | None:
    """The latest release if it is newer than ``current``, else None (network errors propagate)."""
    release = latest_release(get)
    return release if release is not None and release.is_newer_than(current) else None


def check_due(engine: Engine, now: datetime | None = None) -> bool:
    t = schema.app_setting
    with engine.connect() as conn:
        raw = conn.execute(select(t.c.value).where(t.c.key == _STATE_KEY)).scalar_one_or_none()
    if raw is None:
        return True
    try:
        last = datetime.fromisoformat(json.loads(raw)["checked_at"])
    except (ValueError, KeyError, TypeError):
        return True
    return (now or datetime.now()) - last >= CHECK_INTERVAL


def mark_checked(engine: Engine, now: datetime | None = None) -> None:
    value = json.dumps({"checked_at": (now or datetime.now()).isoformat(timespec="seconds")})
    t = schema.app_setting
    with engine.begin() as conn:
        stmt = insert(t).values(key=_STATE_KEY, value=value)
        conn.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={"value": value}))

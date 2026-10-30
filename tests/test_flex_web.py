from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine

from taxfolio.importers.flex_web import FlexWebError, fetch_statement
from taxfolio.services import flex_sync, queries, secrets

SENT = b"""<FlexStatementResponse timestamp="29 October, 2026 01:00 PM EDT">
<Status>Success</Status><ReferenceCode>REF123</ReferenceCode>
<Url>https://example.invalid/GetStatement</Url></FlexStatementResponse>"""
IN_PROGRESS = b"""<FlexStatementResponse><Status>Warn</Status><ErrorCode>1019</ErrorCode>
<ErrorMessage>Statement generation in progress.</ErrorMessage></FlexStatementResponse>"""
BAD_TOKEN = b"""<FlexStatementResponse><Status>Fail</Status><ErrorCode>1015</ErrorCode>
<ErrorMessage>Token is invalid.</ErrorMessage></FlexStatementResponse>"""


def fake_ibkr(*bodies: bytes):  # noqa: ANN201
    calls: list[str] = []
    queue = list(bodies)

    def get(url: str) -> bytes:
        calls.append(url)
        return queue.pop(0)

    return get, calls


def test_fetch_polls_until_statement_is_ready(fixtures: Path) -> None:
    statement = (fixtures / "flex_2025.xml").read_bytes()
    get, calls = fake_ibkr(SENT, IN_PROGRESS, IN_PROGRESS, statement)
    sleeps: list[float] = []
    messages: list[str] = []
    out = fetch_statement("TOKEN", "999", get=get, sleep=sleeps.append, progress=messages.append)
    assert out == statement
    assert "SendRequest?t=TOKEN&q=999&v=3" in calls[0]
    assert calls[1].startswith("https://example.invalid/GetStatement?t=TOKEN&q=REF123&v=3")
    assert len(sleeps) == 3 and any("generuje" in m for m in messages)


def test_fetch_reports_ibkr_error_with_hint() -> None:
    get, _ = fake_ibkr(BAD_TOKEN)
    with pytest.raises(FlexWebError) as err:
        fetch_statement("BAD", "999", get=get, sleep=lambda _s: None)
    assert err.value.code == "1015" and "Nastavení" in str(err.value)


def test_fetch_gives_up_after_max_wait() -> None:
    get, _ = fake_ibkr(SENT, *[IN_PROGRESS] * 10)
    with pytest.raises(FlexWebError) as err:
        fetch_statement("T", "1", get=get, sleep=lambda _s: None, poll_interval=60, max_wait=120)
    assert err.value.code == "1019"


def test_missing_configuration() -> None:
    with pytest.raises(FlexWebError):
        fetch_statement("", "1")


def test_sync_downloads_and_imports(engine: Engine, fixtures: Path, tmp_path: Path) -> None:
    statement = (fixtures / "flex_2025.xml").read_bytes()
    (res,) = flex_sync.sync(engine, "T", "999", dest_dir=tmp_path, fetch=lambda *_a, **_k: statement)
    assert res.source_format == "ibkr_flex_xml" and res.new_rows["trade"] == 3
    (saved,) = tmp_path.glob("flex_999_*.xml")
    assert saved.read_bytes() == statement
    (again,) = flex_sync.sync(engine, "T", "999", dest_dir=tmp_path, fetch=lambda *_a, **_k: statement)
    assert again.total_new == 0  # overlapping periods deduplicate
    assert queries.table_counts(engine)["trade"] == 3


def test_fetch_sends_date_range(fixtures: Path) -> None:
    statement = (fixtures / "flex_2025.xml").read_bytes()
    get, calls = fake_ibkr(statement)
    fetch_statement("T", "999", get=get, from_date=date(2025, 1, 1), to_date=date(2025, 12, 31))
    assert "SendRequest?t=T&q=999&v=3&fd=20250101&td=20251231" in calls[0]


@pytest.mark.parametrize(
    ("start", "end"),
    [(date(2025, 1, 1), None), (date(2024, 1, 1), date(2024, 12, 31)), (date(2025, 2, 1), date(2025, 1, 1))],
)
def test_fetch_rejects_invalid_range(start: date, end: date | None) -> None:
    with pytest.raises(FlexWebError) as err:
        fetch_statement("T", "1", get=lambda _u: b"", from_date=start, to_date=end)
    assert err.value.code == "CFG"


def test_years_are_split_per_year_and_leap_year_in_halves() -> None:
    period = flex_sync.years_period(2023, 2026, today=date(2026, 10, 30))
    assert period.ranges() == [
        (date(2023, 1, 1), date(2023, 12, 31)),
        (date(2024, 1, 1), date(2024, 6, 30)),  # 366 days > IBKR limit of 365
        (date(2024, 7, 1), date(2024, 12, 31)),
        (date(2025, 1, 1), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 10, 29)),  # current year ends yesterday
    ]
    assert flex_sync.QUERY_PERIOD.ranges() == [None]
    with pytest.raises(ValueError):
        flex_sync.years_period(2026, 2026, today=date(2026, 1, 1))  # nothing to download yet


def test_download_statements_one_file_per_range(tmp_path: Path) -> None:
    requested: list[tuple[date, date]] = []
    pauses: list[float] = []

    def fetch(token: str, query_id: str, *, progress: object, from_date: date, to_date: date) -> bytes:
        requested.append((from_date, to_date))
        return b"<FlexQueryResponse/>"

    period = flex_sync.years_period(2024, 2025, today=date(2026, 3, 1))
    paths = flex_sync.download_statements("T", "9", period, tmp_path, fetch=fetch, sleep=pauses.append)
    assert len(paths) == len(requested) == 3 and len(pauses) == 2
    assert sorted(p.name.split("_")[2] for p in paths) == [
        "20240101-20240630",
        "20240701-20241231",
        "20250101-20251231",
    ]


def test_secrets_per_source_in_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    assert secrets.get_secret("a1", "token") is None
    secrets.set_secret("a1", "token", "  abc  ")
    secrets.set_secret("b2", "token", "xyz")
    assert secrets.get_secret("a1", "token") == "abc" and secrets.get_secret("b2", "token") == "xyz"
    monkeypatch.setenv(secrets.ENV_VAR, "from-env")
    assert secrets.env_token() == "from-env"
    secrets.delete_secret("a1", "token")
    secrets.delete_secret("a1", "token")  # deleting twice is fine
    assert secrets.get_secret("a1", "token") is None and secrets.get_secret("b2", "token") == "xyz"


def test_network_outage_is_retried_then_reported(fixtures: Path) -> None:
    import urllib.error

    statement = (fixtures / "flex_2025.xml").read_bytes()
    dns = urllib.error.URLError(OSError(-3, "Temporary failure in name resolution"))
    answers: list[object] = [dns, statement]

    def flaky(_url: str) -> bytes:
        item = answers.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, bytes)
        return item

    pauses: list[float] = []
    messages: list[str] = []
    out = fetch_statement("T", "1", get=flaky, sleep=pauses.append, progress=messages.append)
    assert out == statement and pauses == [3.0] and any("znovu" in m for m in messages)

    def down(_url: str) -> bytes:
        raise dns

    with pytest.raises(FlexWebError) as err:
        fetch_statement("T", "1", get=down, sleep=lambda _s: None)
    assert err.value.code == "NET" and "připojení k internetu" in str(err.value)
    assert "ndcdyn.interactivebrokers.com" in str(err.value)


def test_source_error_is_reported_once(engine: Engine) -> None:
    from taxfolio.services import source_sync
    from taxfolio.services.sources import InputSource, SourceType

    secrets.set_secret("s1", "token", "T")
    source = InputSource(SourceType.IBKR_FLEX, "IBKR", {"query_id": "1"}, id="s1")

    def fail(*_a: object, **_k: object) -> bytes:
        raise FlexWebError("NET", "offline")

    log: list[str] = []
    (result,) = source_sync.fetch_all([source], progress=log.append, fetch=fail)
    assert "offline" in result.error
    assert not any("offline" in line for line in log)  # the summary prints it, not the progress log


def test_stop_interrupts_waiting_for_ibkr(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading
    import time

    from taxfolio.importers import flex_web
    from taxfolio.services import source_sync
    from taxfolio.services.sources import InputSource, SourceType

    answers = iter([SENT, *[IN_PROGRESS] * 100])
    monkeypatch.setattr(flex_web, "http_get", lambda _url, timeout=30: next(answers))
    secrets.set_secret("s9", "token", "T")
    source = InputSource(SourceType.IBKR_FLEX, "IBKR", {"query_id": "1"}, id="s9")
    cancel = threading.Event()
    threading.Timer(0.2, cancel.set).start()  # the user presses Stop while IBKR generates
    started = time.monotonic()
    with pytest.raises(source_sync.Cancelled):
        source_sync.fetch_all([source], cancel=cancel)  # would poll every 5 s for minutes
    assert time.monotonic() - started < 2

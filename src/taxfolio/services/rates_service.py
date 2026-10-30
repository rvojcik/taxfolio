"""Keep official exchange rates in the local database and build converters from them."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta

from sqlalchemy import Engine, select
from sqlalchemy.dialects.sqlite import insert

from taxfolio.fx import sources
from taxfolio.fx.converter import FxConverter
from taxfolio.fx.sources import CNB, ECB, RateRow
from taxfolio.storage import schema

# The running year keeps getting new fixings; refresh it at most this often.
CURRENT_YEAR_REFRESH = timedelta(hours=12)

# Reports call ensure_rates; the desktop app turns this off and downloads in a background thread
# instead (download_rates), so a slow or broken network never blocks the window.
_auto_download = True


def set_auto_download(enabled: bool) -> None:
    global _auto_download
    _auto_download = enabled


def missing_years(engine: Engine, years: Iterable[int]) -> dict[str, list[int]]:
    t = schema.reference_rate_year
    with engine.connect() as conn:
        fetched = {
            (r.source, r.year): r.fetched_at
            for r in conn.execute(select(t.c.source, t.c.year, t.c.fetched_at))
        }
    now = datetime.now()

    def stale(source: str, year: int) -> bool:
        when = fetched.get((source, year))
        if when is None:
            return True
        # A past year is complete once it was fetched after its end.
        return when.year <= year and now - when > CURRENT_YEAR_REFRESH

    return {
        source: sorted(y for y in set(years) if y <= now.year and stale(source, y)) for source in (CNB, ECB)
    }


def ensure_rates(
    engine: Engine,
    years: Iterable[int],
    fetch_cnb: Callable[[int], list[RateRow]] | None = None,
    fetch_ecb_years: Callable[[set[int]], list[RateRow]] | None = None,
) -> list[str]:
    """Download missing years (unless turned off by set_auto_download). Returns notes on what was fetched."""
    if not _auto_download:
        return []
    return download_rates(engine, years, fetch_cnb, fetch_ecb_years)


def download_rates(
    engine: Engine,
    years: Iterable[int],
    fetch_cnb: Callable[[int], list[RateRow]] | None = None,
    fetch_ecb_years: Callable[[set[int]], list[RateRow]] | None = None,
) -> list[str]:
    """Download the missing years now, whatever set_auto_download says (background thread, CLI)."""
    # Resolved at call time so tests can replace the network fetchers on the module.
    fetch_cnb = fetch_cnb or sources.fetch_cnb_year
    fetch_ecb_years = fetch_ecb_years or sources.fetch_ecb
    years = set(years)
    # Unified annual rate for year Y needs the 31 Dec fixing; previous-year January dates may fall
    # back to the last December fixing, so include Y-1 as well.
    wanted = years | {y - 1 for y in years}
    todo = missing_years(engine, wanted)
    notes: list[str] = []
    for year in todo[CNB]:
        _store(engine, CNB, year, fetch_cnb(year))
        notes.append(f"ČNB {year}")
    if todo[ECB]:
        rows = fetch_ecb_years(set(todo[ECB]))
        for year in todo[ECB]:
            _store(engine, ECB, year, [r for r in rows if r.date.year == year])
        notes.append("ECB " + ", ".join(map(str, todo[ECB])))
    return notes


def _store(engine: Engine, source: str, year: int, rows: list[RateRow]) -> None:
    t = schema.reference_rate
    with engine.begin() as conn:
        if rows:
            stmt = insert(t)
            conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=["source", "currency", "date"], set_={"rate": stmt.excluded.rate}
                ),
                [{"source": r.source, "currency": r.currency, "date": r.date, "rate": r.rate} for r in rows],
            )
        y = schema.reference_rate_year
        stmt_y = insert(y).values(source=source, year=year, fetched_at=datetime.now())
        conn.execute(
            stmt_y.on_conflict_do_update(
                index_elements=["source", "year"], set_={"fetched_at": datetime.now()}
            )
        )


def load_converter(engine: Engine) -> FxConverter:
    """Converter with official rates, IBKR rates from Flex statements and the user's rate rules."""
    from taxfolio.services.settings import load_settings

    t, ib = schema.reference_rate, schema.fx_rate
    with engine.connect() as conn:
        rows = [
            RateRow(r.source, r.currency, r.date, r.rate)
            for r in conn.execute(select(t.c.source, t.c.currency, t.c.date, t.c.rate))
        ]
        ibkr = [
            (r.date, r.from_currency, r.to_currency, r.rate)
            for r in conn.execute(select(ib.c.date, ib.c.from_currency, ib.c.to_currency, ib.c.rate))
        ]
    return FxConverter(rows, rules=load_settings(engine).rate_rules, ibkr_rows=ibkr)


def used_currencies(engine: Engine) -> list[str]:
    """Currencies that appear in trades, cash movements or positions."""
    tables = (schema.trade.c.currency, schema.cash_transaction.c.currency, schema.open_position.c.currency)
    found: set[str] = set()
    with engine.connect() as conn:
        for col in tables:
            found.update(c for c in conn.execute(select(col).distinct()).scalars() if c)
    return sorted(found)

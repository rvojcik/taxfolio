"""Smoke test against the user's real exports, if present locally (never committed)."""

from pathlib import Path

import pytest
from sqlalchemy import Engine

from taxfolio.services import import_service, queries

DATA = Path(__file__).parent.parent / "data_examples"


@pytest.mark.skipif(not DATA.is_dir(), reason="data_examples/ not available")
def test_all_real_exports_import_cleanly(engine: Engine) -> None:
    files = sorted([*DATA.glob("*.csv"), *DATA.glob("*.xml")])
    assert files
    for f in files:
        import_service.import_file(engine, f)
    for f in files:
        assert import_service.import_file(engine, f).total_new == 0, f.name
    stock_trades = queries.list_trades(engine, asset_class="STK")
    assert stock_trades
    flex_years = {int(p.stem.rsplit("_", 1)[-1]) for p in DATA.glob("taxfolio_full_*.xml")}
    # Within the years covered by Flex Queries every stock execution knows its order type
    assert all(t.order_type for t in stock_trades if t.trade_datetime.year in flex_years)


@pytest.mark.skipif(not list(DATA.glob("*.xml")) if DATA.is_dir() else True, reason="no Flex exports")
def test_fifo_matches_ibkr_on_real_data(engine: Engine) -> None:
    from taxfolio.services import realized

    for f in sorted([*DATA.glob("*.csv"), *DATA.glob("*.xml")]):
        import_service.import_file(engine, f)
    report = realized.compute_fifo(engine)
    assert report.result.matches
    assert report.result.warnings == []
    assert realized.check_against_ibkr(engine, report) == []

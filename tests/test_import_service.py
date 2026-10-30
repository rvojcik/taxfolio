from pathlib import Path

from sqlalchemy import Engine, select

from taxfolio.services import import_service, queries
from taxfolio.storage import schema


def test_reimport_creates_no_duplicates(engine: Engine, fixtures: Path) -> None:
    first = import_service.import_file(engine, fixtures / "activity_2025.csv")
    second = import_service.import_file(engine, fixtures / "activity_2025.csv")
    assert first.total_new > 0 and first.total_duplicate == 0
    assert second.total_new == 0 and second.total_duplicate == first.total_new
    assert queries.table_counts(engine)["trade"] == 5


def test_identical_rows_in_one_file_are_kept(engine: Engine, fixtures: Path, tmp_path: Path) -> None:
    text = (fixtures / "activity_2025.csv").read_text()
    row = (
        'Trades,Data,Order,Stocks,USD,AAPL,"2025-02-13, 10:57:30",'
        "2,239.14,241.53,-478.28,-1.000092,479.280092,0,4.78,O\n"
    )
    doubled = tmp_path / "doubled.csv"
    doubled.write_text(text.replace(row, row + row))
    import_service.import_file(engine, doubled)
    assert queries.table_counts(engine)["trade"] == 6


def test_undo_import(engine: Engine, fixtures: Path) -> None:
    res = import_service.import_file(engine, fixtures / "activity_2025.csv")
    import_service.undo_import(engine, res.batch_id)
    assert queries.table_counts(engine)["trade"] == 0
    assert queries.list_batches(engine) == []


def test_dividend_country_applied_in_any_import_order(engine: Engine, fixtures: Path) -> None:
    import_service.import_file(engine, fixtures / "dividends_2025.csv")
    import_service.import_file(engine, fixtures / "activity_2025.csv")
    with engine.connect() as conn:
        country = conn.execute(
            select(schema.instrument.c.issuer_country).where(schema.instrument.c.conid == "272997")
        ).scalar_one()
    assert country == "US"


def test_trades_resolve_isin_through_symbol_alias(engine: Engine, fixtures: Path) -> None:
    import_service.import_file(engine, fixtures / "activity_2025.csv")
    trades = {t.symbol: t for t in queries.list_trades(engine, asset_class="STK")}
    assert trades["EXSAd"].isin == "DE0002635307"
    assert queries.available_years(engine) == [2025]


def test_flex_replaces_activity_statement_rows(engine: Engine, fixtures: Path) -> None:
    import_service.import_file(engine, fixtures / "activity_2025.csv")
    res = import_service.import_file(engine, fixtures / "flex_2025.xml")
    assert any("Nahrazeno" in w for w in res.warnings)
    trades = queries.list_trades(engine)
    assert {t.order_type for t in trades} == {"LMT", "STP", "MKT"}  # only Flex executions left
    assert queries.table_counts(engine)["closed_lot"] == 1


def test_activity_statement_skipped_where_flex_exists(engine: Engine, fixtures: Path) -> None:
    import_service.import_file(engine, fixtures / "flex_2025.xml")
    res = import_service.import_file(engine, fixtures / "activity_2025.csv")
    assert res.new_rows.get("trade", 0) == 0
    assert any("Přeskočeno" in w for w in res.warnings)
    assert queries.table_counts(engine)["trade"] == 3

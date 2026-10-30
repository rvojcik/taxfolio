from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine

from taxfolio.engine.exit_classifier import TradeReason
from taxfolio.services import import_service
from taxfolio.services.overview import _bucket, _months, _top, build_overview

D = Decimal


def test_month_axis_and_quarter_buckets() -> None:
    assert _months(2025, [])[0] == "2025-01" and len(_months(2025, [])) == 12
    months = [(f"{y}-{m:02d}", D(1)) for y in (2024, 2025) for m in range(1, 13)]
    quarters = _bucket(months)
    assert quarters[0] == ("Q1/24", D(3)) and len(quarters) == 8
    assert _bucket(months[:12]) == months[:12]
    years = [(f"{y}-{m:02d}", D(1)) for y in range(2015, 2026) for m in range(1, 13)]
    assert _bucket(years)[0] == ("2015", D(12)) and len(_bucket(years)) == 11  # > 24 quarters → years


def test_top_folds_rest_into_other() -> None:
    values = {f"S{i}": D(i) for i in range(1, 14)}
    top = _top(values, key=lambda v: v)
    assert len(top) == 11 and top[0] == ("S13", D(13)) and top[-1] == ("Ostatní", D(6))


def test_overview_from_flex_fixture(engine: Engine, fixtures: Path) -> None:
    import_service.import_file(engine, fixtures / "flex_2025.xml")
    ov = build_overview(engine, 2025, "CZK")  # conftest serves 22 CZK/USD
    assert ov.realized_pnl == D("78.6") * 22
    assert ov.closed_trades == 1 and ov.win_rate == 1
    assert [(r.reason, r.count) for r in ov.reasons] == [(TradeReason.STOP_LOSS, 1)]
    assert ov.dividends_gross == D("1.16") * 22 and ov.withholding == D("0.17") * 22
    assert ov.portfolio_value == 750 * D(22) and ov.unrealized_pnl == 150 * D(22)
    assert ov.holdings == [("AAPL", 750 * D(22))]
    usd = build_overview(engine, 2025, "USD")
    assert usd.realized_pnl == D("78.6") and usd.portfolio_value == 750


def test_dividends_by_company(engine: Engine, fixtures: Path) -> None:
    import_service.import_file(engine, fixtures / "flex_2025.xml")
    ov = build_overview(engine, 2025, "USD")
    (cost,) = ov.dividends_by_company
    assert (cost.symbol, cost.name, cost.country) == ("COST", "COSTCO WHOLESALE CORP", "US")
    assert (cost.payments, cost.gross, cost.withheld, cost.net) == (1, D("1.16"), D("0.17"), D("0.99"))


def test_all_years_axis_starts_with_first_activity_and_shows_cash_flow(engine: Engine) -> None:
    """Test portfolio: deposits and purchases in 2021–2022, first sale only in 2024."""
    data = Path(__file__).parent.parent / "test_data"
    for year in range(2021, 2026):
        import_service.import_file(engine, data / f"flex_{year}.xml")
    ov = build_overview(engine, None, "CZK")
    assert ov.monthly_pnl[0][0] == "Q1/21" and ov.monthly_pnl[-1][0] == "Q3/25"
    deposits = dict(ov.monthly_deposits)
    assert deposits["Q1/21"] == 100_000 and deposits["Q1/22"] == 200_000
    assert sum(deposits.values()) == ov.deposits == 300_000
    assert [p for p, _ in ov.monthly_withdrawals] == [p for p, _ in ov.monthly_deposits]
    assert ov.portfolio_value is not None and ov.portfolio_value > 0  # year-end open positions

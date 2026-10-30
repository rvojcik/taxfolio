from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from taxfolio.fx.converter import CzkMethod
from taxfolio.fx.sources import CNB, ECB
from taxfolio.services import import_service, rates_service
from taxfolio.services.simulator import holdings, simulate_sale
from tests.test_realized import _flat_rates


@pytest.fixture
def loaded(engine: Engine, fixtures: Path) -> Engine:
    import_service.import_file(engine, fixtures / "flex_2025.xml")
    rates_service.ensure_rates(
        engine,
        [2025, 2026],
        fetch_cnb=_flat_rates(CNB, "USD", "22"),
        fetch_ecb_years=_flat_rates(ECB, "USD", "1.1"),
    )
    return engine


def test_holdings_with_last_price(loaded: Engine) -> None:
    (aapl,) = holdings(loaded)
    assert aapl.symbol == "AAPL" and aapl.quantity == 3
    assert aapl.last_price == Decimal(250) and aapl.last_price_date == date(2025, 12, 31)


def test_small_sale_stays_under_czech_limit(loaded: Engine) -> None:
    (aapl,) = holdings(loaded)
    sim = simulate_sale(loaded, aapl, Decimal(3), Decimal(300), date(2025, 12, 1), CzkMethod.CNB_DAILY)
    assert sim.cz_limit_applies_after and sim.cz_delta == 0
    (lot,) = sim.lots
    assert lot.match.quantity == 3 and lot.match.pnl == Decimal(900) - Decimal("600.6")
    # SK: held < 1 year, gain ~272 € is covered by the 500 € exemption on top of the existing sale
    assert sim.sk_delta == 0
    assert any("CZ" in n for n in sim.notes)


def test_large_sale_is_taxed_and_lot_exempt_in_sk_after_one_year(loaded: Engine) -> None:
    (aapl,) = holdings(loaded)
    sim = simulate_sale(loaded, aapl, Decimal(3), Decimal(5000), date(2026, 3, 1), CzkMethod.CNB_DAILY)
    assert not sim.cz_limit_applies_after
    expected_base = (Decimal(15000) - Decimal("600.6")) * 22
    assert sim.cz_delta == expected_base * Decimal("0.15")
    assert sim.lots[0].sk_exempt and sim.sk_delta == 0


def test_invalid_quantity(loaded: Engine) -> None:
    (aapl,) = holdings(loaded)
    with pytest.raises(ValueError):
        simulate_sale(loaded, aapl, Decimal(4), Decimal(1), date(2025, 12, 1), CzkMethod.CNB_DAILY)


def test_impact_timeline_drops_to_zero_after_time_tests(loaded: Engine) -> None:
    from taxfolio.services.simulator import impact_timeline

    (aapl,) = holdings(loaded)
    sim = simulate_sale(loaded, aapl, Decimal(3), Decimal(5000), date(2025, 12, 1), CzkMethod.CNB_DAILY)
    assert sim.cz_delta > 0 and sim.sk_delta > 0
    timeline = impact_timeline(loaded, sim, czk_method=CzkMethod.CNB_DAILY)
    days = [p.sale_date for p in timeline]
    assert days[0] == sim.sale_date and days == sorted(days)
    (lot,) = sim.lots
    by_day = {p.sale_date: p for p in timeline}
    assert date(2026, 1, 1) in by_day  # a new tax year without the year's other sales
    assert by_day[lot.sk_exempt_from].sk_delta == 0
    assert by_day[lot.cz_exempt_from].cz_delta == 0  # a year without rules uses the latest ones
    assert by_day[timeline[0].sale_date].cz_delta == sim.cz_delta

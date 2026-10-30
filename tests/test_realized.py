from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine

from taxfolio.fx.converter import CzkMethod
from taxfolio.fx.sources import CNB, ECB, RateRow
from taxfolio.services import import_service, rates_service, realized


def _flat_rates(source: str, currency: str, rate: str):
    def fetch(years):
        years = {years} if isinstance(years, int) else years
        out = []
        for y in years:
            d = date(y, 1, 1)
            while d.year == y:
                out.append(RateRow(source, currency, d, Decimal(rate)))
                d += timedelta(days=1)
        return out

    return fetch


def test_realized_gain_in_czk_and_eur(engine: Engine, fixtures: Path) -> None:
    import_service.import_file(engine, fixtures / "flex_2025.xml")
    rates_service.ensure_rates(
        engine,
        [2025],
        fetch_cnb=_flat_rates(CNB, "USD", "22"),
        fetch_ecb_years=_flat_rates(ECB, "USD", "1.1"),
    )
    report = realized.compute_fifo(engine)
    (row,) = realized.realized_rows(report, rates_service.load_converter(engine), CzkMethod.CNB_DAILY, 2025)
    assert row.match.quantity == 2
    assert row.match.pnl == Decimal("78.6")  # 479 net proceeds − 2/5 × 1001
    assert row.pnl_czk == Decimal("78.6") * 22
    assert round(row.pnl_eur, 6) == round(Decimal("78.6") / Decimal("1.1"), 6)
    assert realized.check_against_ibkr(engine, report) == []


def test_ensure_rates_downloads_each_year_once(engine: Engine) -> None:
    calls: list[int] = []

    def fetch_cnb(year: int):
        calls.append(year)
        return _flat_rates(CNB, "USD", "22")(year)

    for _ in range(2):
        rates_service.ensure_rates(
            engine, [2020], fetch_cnb=fetch_cnb, fetch_ecb_years=_flat_rates(ECB, "USD", "1.1")
        )
    assert sorted(calls) == [2019, 2020]

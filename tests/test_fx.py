from datetime import date
from decimal import Decimal

import pytest

from taxfolio.fx.converter import CzkMethod, FxConverter, MissingRateError
from taxfolio.fx.sources import CNB, ECB, RateRow, parse_cnb_year, parse_ecb_history

CNB_TEXT = """Datum|1 EUR|100 HUF|1 USD
02.01.2025|25,175|6,097|24,321
03.01.2025|25,200|6,100|24,400
Datum|1 EUR|1 USD
06.01.2025|25,100|24,000
"""


def test_parse_cnb_year_handles_units_and_repeated_header() -> None:
    rows = parse_cnb_year(CNB_TEXT)
    huf = next(r for r in rows if r.currency == "HUF")
    assert huf.rate == Decimal("0.06097")  # CZK per 1 HUF
    assert {r.date for r in rows if r.currency == "USD"} == {
        date(2025, 1, 2),
        date(2025, 1, 3),
        date(2025, 1, 6),
    }
    assert all(r.source == CNB for r in rows)


def test_parse_ecb_history_skips_na_and_filters_years() -> None:
    text = "Date,USD,CZK,CYP,\n2025-01-03,1.0299,25.2,N/A,\n2024-12-31,1.0389,25.185,N/A,\n"
    rows = parse_ecb_history(text, {2025})
    assert [(r.currency, r.rate) for r in rows] == [("USD", Decimal("1.0299")), ("CZK", Decimal("25.2"))]
    assert all(r.source == ECB for r in rows)


def _month_end_rows(year: int, usd: list[str]) -> list[RateRow]:
    import calendar

    return [
        RateRow(CNB, "USD", date(year, m, calendar.monthrange(year, m)[1]), Decimal(v))
        for m, v in zip(range(1, 13), usd, strict=True)
    ]


def test_daily_rate_falls_back_to_last_fixing() -> None:
    fx = FxConverter(parse_cnb_year(CNB_TEXT))
    # Saturday 4.1. and Sunday 5.1. use Friday's fixing
    assert fx.cnb_rate("USD", date(2025, 1, 5)) == Decimal("24.400")
    assert fx.to_czk(Decimal(10), "USD", date(2025, 1, 6), CzkMethod.CNB_DAILY) == Decimal("240.000")
    assert fx.cnb_rate("CZK", date(2025, 1, 5)) == 1


def test_missing_rate_raises() -> None:
    fx = FxConverter(parse_cnb_year(CNB_TEXT))
    with pytest.raises(MissingRateError):
        fx.cnb_rate("USD", date(2024, 12, 31))
    with pytest.raises(MissingRateError):
        fx.cnb_rate("GBP", date(2025, 1, 3))


def test_unified_rate_is_average_of_month_end_rates() -> None:
    values = ["20", "21", "22", "23", "24", "25", "20", "21", "22", "23", "24", "25.1"]
    fx = FxConverter(_month_end_rows(2025, values))
    assert fx.unified_rate("USD", 2025) == Decimal("22.51")  # 270.1 / 12 = 22.508…
    assert fx.czk_rate("USD", date(2025, 3, 15), CzkMethod.GFR_ANNUAL) == Decimal("22.51")


def test_unified_rate_override() -> None:
    fx = FxConverter([], unified_overrides={("USD", 2024): Decimal("23.28")})
    assert fx.unified_rate("USD", 2024) == Decimal("23.28")


def test_to_eur_divides_by_ecb_rate() -> None:
    fx = FxConverter([RateRow(ECB, "USD", date(2025, 1, 3), Decimal("1.25"))])
    assert fx.to_eur(Decimal(100), "USD", date(2025, 1, 4)) == Decimal(80)
    assert fx.to_eur(Decimal(100), "EUR", date(2025, 1, 4)) == Decimal(100)


def test_rate_rules_sources_and_fixed() -> None:
    from taxfolio.fx.converter import RateRule, RateSource

    rows = [
        RateRow(CNB, "USD", date(2025, 3, 3), Decimal("22")),
        RateRow(CNB, "EUR", date(2025, 3, 3), Decimal("25")),
        RateRow(ECB, "USD", date(2025, 3, 3), Decimal("1.1")),
        RateRow(ECB, "CZK", date(2025, 3, 3), Decimal("24.2")),
    ]
    ibkr = [
        (date(2025, 3, 3), "USD", "EUR", Decimal("0.9")),
        (date(2025, 3, 3), "CZK", "EUR", Decimal("0.04")),
    ]
    day = date(2025, 3, 4)
    fx = FxConverter(rows, ibkr_rows=ibkr)
    assert fx.rate("USD", day, "CZK") == Decimal("22")  # default ČNB
    assert fx.rate("USD", day, "EUR") == Decimal(1) / Decimal("1.1")  # default ECB
    assert fx.rate("USD", day, "CZK", RateSource.ECB_DAILY) == Decimal("24.2") / Decimal("1.1")
    assert fx.rate("USD", day, "EUR", RateSource.CNB_DAILY) == Decimal("22") / Decimal("25")
    assert fx.rate("USD", day, "CZK", RateSource.IBKR_DAILY) == Decimal("0.9") / Decimal("0.04")
    assert fx.rate("USD", day, "EUR", RateSource.IBKR_DAILY) == Decimal("0.9")
    with pytest.raises(MissingRateError):
        fx.rate("USD", day, "CZK", RateSource.FIXED)  # no value to preview

    fixed = FxConverter(rows, rules={("CZK", "USD"): RateRule(RateSource.FIXED, Decimal("20"))})
    assert fixed.to_czk(Decimal(10), "USD", day) == Decimal(200)
    assert fixed.to_czk(Decimal(10), "USD", day, CzkMethod.CNB_DAILY) == Decimal(220)  # explicit override
    assert "pevný 20" in fixed.describe("CZK", ["USD", "CZK"])
    assert fixed.latest_date(RateSource.CNB_DAILY, "USD") == date(2025, 3, 3)


def test_settings_roundtrip(tmp_path) -> None:  # noqa: ANN001
    from taxfolio.fx.converter import RateRule, RateSource
    from taxfolio.services.settings import AppSettings, load_settings, save_settings
    from taxfolio.storage.db import open_db

    engine = open_db(tmp_path / "s.sqlite")
    assert load_settings(engine).tax_country == "CZ"
    s = AppSettings(tax_country="SK")
    s.rate_rules[("CZK", "USD")] = RateRule(RateSource.FIXED, Decimal("21.5"))
    s.rate_rules[("EUR", "USD")] = RateRule(RateSource.ECB_DAILY)  # default → not stored
    save_settings(engine, s)
    loaded = load_settings(engine)
    assert loaded.tax_country == "SK"
    assert loaded.rate_rules == {("CZK", "USD"): RateRule(RateSource.FIXED, Decimal("21.5"))}
    assert loaded.rule("EUR", "GBP").source is RateSource.ECB_DAILY

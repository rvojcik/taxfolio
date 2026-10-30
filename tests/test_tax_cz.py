from datetime import date, datetime
from decimal import Decimal

from taxfolio.engine.lots import LotMatch
from taxfolio.fx.converter import CzkMethod, FxConverter
from taxfolio.services.dividends import DividendEvent
from taxfolio.services.realized import RealizedRow
from taxfolio.tax.cz import EXEMPT_LIMIT, EXEMPT_TIME_TEST, compute_cz, time_test_date
from taxfolio.tax.rules_loader import load_cz

D = Decimal
FX = FxConverter([])  # CZK amounts only → no rates needed


def sale(opened: str, closed: str, cost: str, proceeds: str, comm: str = "0") -> RealizedRow:
    m = LotMatch(
        key="X",
        symbol="X",
        currency="CZK",
        open_ref=1,
        close_ref=2,
        open_datetime=datetime.fromisoformat(opened),
        close_datetime=datetime.fromisoformat(closed),
        quantity=D(1),
        cost=D(cost),
        proceeds=D(proceeds) + D(comm),
        sell_commission=D(comm),
    )
    return RealizedRow(m, "", "", D(cost), m.proceeds, D(0), D(0), sell_commission_czk=D(comm))


def div(country: str, gross: str, tax: str, day: str = "2025-05-01", ccy: str = "CZK") -> DividendEvent:
    d = date.fromisoformat(day)
    return DividendEvent(
        key=f"{country}{gross}",
        symbol="S",
        isin="",
        country=country,
        currency=ccy,
        pay_date=d,
        gross=D(gross),
        withheld=D(tax),
        income_rows=[(d, D(gross))],
        tax_rows=[(d, D(tax))],
    )


def test_time_test_must_exceed_three_years() -> None:
    assert time_test_date(date(2022, 3, 10), 3) == date(2025, 3, 11)
    assert time_test_date(date(2024, 2, 29), 3) == date(2027, 3, 1)


def test_rules_per_year() -> None:
    assert load_cz(2025).time_test_cap == D(40_000_000)
    assert load_cz(2026).time_test_cap is None
    assert load_cz(2024).higher_rate_threshold == D(1_582_812)


def test_all_sales_exempt_under_gross_limit() -> None:
    rep = compute_cz(
        2025, load_cz(2025), CzkMethod.CNB_DAILY, [sale("2025-01-02", "2025-06-01", "50000", "90000")], [], FX
    )
    assert rep.securities.limit_applies
    assert rep.sales[0].exempt_reason == EXEMPT_LIMIT
    assert rep.securities.partial_base == 0 and rep.tax_total == 0


def test_limit_counts_gross_income_not_profit() -> None:
    # Profit is only 1 000 Kč but the sale price exceeds 100 000 Kč → taxable
    rep = compute_cz(
        2025,
        load_cz(2025),
        CzkMethod.CNB_DAILY,
        [sale("2025-01-02", "2025-06-01", "100000", "101000")],
        [],
        FX,
    )
    assert not rep.securities.limit_applies
    assert rep.securities.partial_base == D(1000)
    assert rep.tax_securities == D(150)


def test_time_tested_lot_is_exempt_and_losses_net_to_zero() -> None:
    rows = [
        sale("2021-01-04", "2025-06-01", "10000", "200000"),  # > 3 years → exempt
        sale("2025-01-02", "2025-06-01", "60000", "50000", "-100"),  # loss 10 100
        sale("2025-02-02", "2025-06-01", "60000", "65000"),  # gain 5 000
    ]
    rep = compute_cz(2025, load_cz(2025), CzkMethod.CNB_DAILY, rows, [], FX)
    s = rep.securities
    assert [line.exempt_reason for line in rep.sales] == [EXEMPT_TIME_TEST, None, None]
    assert s.time_test_income == D(200000)
    assert s.taxable_income == D(115000)  # gross sale prices (commission is an expense)
    assert s.taxable_expenses == D(120100)
    assert s.taxable_difference == D(-5100) and s.partial_base == 0
    assert any("ztrátou" in w for w in rep.warnings)


def test_limit_may_exclude_time_tested_income() -> None:
    from dataclasses import replace

    rules = replace(load_cz(2025), limit_includes_time_tested=False)
    rows = [
        sale("2021-01-04", "2025-06-01", "10000", "500000"),
        sale("2025-01-02", "2025-06-01", "50000", "60000"),
    ]
    rep = compute_cz(2025, rules, CzkMethod.CNB_DAILY, rows, [], FX)
    assert rep.securities.limit_applies and rep.securities.partial_base == 0


def test_foreign_dividend_credit_capped_by_treaty_and_domestic_out_of_return() -> None:
    events = [
        div("US", "1000", "150"),
        div("DE", "1000", "263.75"),
        div("CZ", "1000", "350"),
        div("LU", "100", "0"),
    ]
    rep = compute_cz(2025, load_cz(2025), CzkMethod.CNB_DAILY, [], events, FX)
    by = {d.country: d for d in rep.dividends}
    assert by["US"].credit == D(150) and by["US"].tax_due == 0
    assert by["DE"].credit == D(150) and by["DE"].not_creditable == D("113.75")
    assert by["LU"].tax_due == D(15)
    assert by["CZ"].domestic and by["CZ"].tax_due == 0
    assert rep.foreign_dividend_income == D(2100)
    assert rep.tax_total == D(315) - D(300)
    assert any("DE" in w for w in rep.warnings) and any("Tuzemské" in w for w in rep.warnings)


def test_dividends_of_other_years_ignored() -> None:
    rep = compute_cz(2025, load_cz(2025), CzkMethod.CNB_DAILY, [], [div("US", "100", "15", "2024-12-31")], FX)
    assert rep.dividends == []


def test_higher_rate_estimate_matches_base_rate_formula() -> None:
    rep = compute_cz(
        2025,
        load_cz(2025),
        CzkMethod.CNB_DAILY,
        [sale("2025-01-02", "2025-06-01", "100000", "110000")],
        [div("US", "1000", "150"), div("LU", "100", "0")],
        FX,
    )
    assert rep.tax_total_at(rep.rules.rate) == rep.tax_total
    # 23 %: the credit stays capped by the treaty rate, so only the Czech side grows
    assert rep.tax_total_higher == rep.tax_total + (
        rep.securities.partial_base + rep.foreign_dividend_income
    ) * (rep.rules.higher_rate - rep.rules.rate)
    assert rep.tax_total_higher == D(10000) * D("0.23") + D(1100) * D("0.23") - D(150)


def test_rules_2021_to_2023_use_48_times_average_wage() -> None:
    thresholds = {2021: 1_701_168, 2022: 1_867_728, 2023: 1_935_552, 2024: 1_582_812}
    for year, threshold in thresholds.items():
        rules = load_cz(year)
        assert rules.higher_rate_threshold == D(threshold) and rules.time_test_years == 3
        assert rules.gross_income_limit == D(100_000) and rules.time_test_cap is None

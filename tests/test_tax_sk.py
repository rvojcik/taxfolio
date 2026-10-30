from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from taxfolio.engine.lots import LotMatch
from taxfolio.fx.converter import FxConverter
from taxfolio.services.dividends import DividendEvent
from taxfolio.services.realized import RealizedRow
from taxfolio.tax.rules_loader import load_sk
from taxfolio.tax.sk import compute_sk

D = Decimal
FX = FxConverter([])  # EUR amounts only


def sale(
    opened: str, closed: str, cost: str, proceeds: str, key: str = "US1", comm: str = "0"
) -> RealizedRow:
    m = LotMatch(
        key=key,
        symbol=key,
        currency="EUR",
        open_ref=1,
        close_ref=2,
        open_datetime=datetime.fromisoformat(opened),
        close_datetime=datetime.fromisoformat(closed),
        quantity=D(1),
        cost=D(cost),
        proceeds=D(proceeds) + D(comm),
        sell_commission=D(comm),
    )
    return RealizedRow(m, "", "", D(0), D(0), D(cost), m.proceeds, sell_commission_eur=D(comm))


EXCH = {"US1": "NASDAQ", "OTC": "PINK"}


def div(country: str, gross: str, tax: str, day: str = "2025-05-01") -> DividendEvent:
    d = date.fromisoformat(day)
    return DividendEvent(
        key=f"{country}-{day}",
        symbol="S",
        isin="",
        country=country,
        currency="EUR",
        pay_date=d,
        gross=D(gross),
        withheld=D(tax),
        income_rows=[(d, D(gross))],
        tax_rows=[(d, D(tax))],
    )


def test_progressive_brackets() -> None:
    r24, r26 = load_sk(2024), load_sk(2026)
    assert r24.income_tax(D(1000)) == D(190)
    assert r24.income_tax(D(50000)) == D("47537.98") * D("0.19") + (D(50000) - D("47537.98")) * D("0.25")
    assert r26.income_tax(D(80000)) == (
        D("43983.32") * D("0.19")
        + (D("60349.21") - D("43983.32")) * D("0.25")
        + (D("75010.32") - D("60349.21")) * D("0.30")
        + (D(80000) - D("75010.32")) * D("0.35")
    )


def test_one_year_on_regulated_market_is_exempt_otc_is_not() -> None:
    rows = [
        sale("2024-01-02", "2025-01-03", "1000", "3000"),  # > 1 year, NASDAQ → exempt
        sale("2024-01-02", "2025-01-03", "1000", "3000", key="OTC"),  # > 1 year, but OTC → taxable
        sale("2024-06-01", "2025-01-03", "1000", "1200"),  # < 1 year → taxable
    ]
    rep = compute_sk(2025, load_sk(2025), rows, [], FX, EXCH)
    assert [line.taxable for line in rep.sales] == [False, True, True]
    s = rep.securities
    assert s.exempt_income == D(3000)
    assert s.difference == D(2200) and s.exemption_used == D(500) and s.base == D(1700)
    assert rep.tax_securities == D(1700) * D("0.19")
    assert rep.health_insurance == D(1700) * D("0.16")
    assert any("PINK" in w for w in rep.warnings)


def test_small_gain_fully_covered_by_500_and_loss_ignored() -> None:
    rep = compute_sk(2025, load_sk(2025), [sale("2025-01-02", "2025-03-01", "1000", "1400")], [], FX, EXCH)
    assert rep.securities.exemption_used == D(400) and rep.securities.base == 0
    rep = compute_sk(2025, load_sk(2025), [sale("2025-01-02", "2025-03-01", "1000", "600")], [], FX, EXCH)
    assert rep.securities.base == 0 and rep.securities.exemption_used == 0


def test_exempt_sales_do_not_offset_taxable_losses() -> None:
    rows = [
        sale("2023-01-02", "2025-03-01", "5000", "1000"),
        sale("2025-01-02", "2025-03-01", "1000", "2000"),
    ]
    rep = compute_sk(2025, load_sk(2025), rows, [], FX, EXCH)
    assert rep.securities.base == D(500)  # 1000 gain − 500 exemption; the exempt loss is irrelevant


def test_exemption_used_elsewhere() -> None:
    rep = compute_sk(
        2025,
        load_sk(2025),
        [sale("2025-01-02", "2025-03-01", "1000", "1400")],
        [],
        FX,
        EXCH,
        exemption_used_elsewhere=True,
    )
    assert rep.securities.base == D(400)


def test_dividend_rate_by_profit_year_and_credit() -> None:
    rules = load_sk(2025)
    events = [div("US", "100", "15"), div("CZ", "100", "35")]
    rep = compute_sk(2025, rules, [], events, FX, EXCH)
    by = {d.country: d for d in rep.dividends}
    assert by["US"].profit_year == 2024 and by["US"].rate == D("0.10")
    assert by["US"].credit == D(10) and by["US"].tax_due == 0  # credit capped by Slovak tax
    assert by["CZ"].credit == D(10)
    rep26 = compute_sk(2026, load_sk(2026), [], [div("US", "100", "0", "2026-03-01")], FX, EXCH)
    assert rep26.dividends[0].rate == D("0.07") and rep26.tax_total == D(7)


def test_profit_year_override_and_non_cooperating_state() -> None:
    rules = replace(load_sk(2025), non_cooperating_states=frozenset({"XX"}))
    events = [div("US", "100", "0"), div("XX", "100", "0")]
    rep = compute_sk(2025, rules, [], events, FX, EXCH, profit_year_overrides={"US-2025-05-01": 2015})
    by = {d.country: d for d in rep.dividends}
    assert by["US"].rate is None and by["US"].sk_tax == 0
    assert by["XX"].rate == D("0.35")


def test_rules_2021_to_2023_brackets() -> None:
    from taxfolio.tax.rules_loader import load_sk

    # 176.8 × subsistence minimum valid on 1 January of the year
    for year, limit in {2021: "37981.94", 2022: "38553.01", 2023: "41445.46"}.items():
        rules = load_sk(year)
        assert rules.brackets[0].up_to == Decimal(limit) and rules.time_test_years == 1
        assert rules.dividend_rate("US", year - 1) == Decimal("0.07")

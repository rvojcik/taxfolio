"""The fictional test portfolio in test_data/ (scenarios: test_data/README.md).

Tests run with the flat rates of conftest.py (1 USD = 22 CZK, 1 EUR = 24.2 CZK = 1.1 USD), so the
foreign-currency scenarios have exact expected values too. CZK values come from
test_data/expected_cz.json, which the generator computes independently of the app.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from taxfolio.fx.converter import CzkMethod
from taxfolio.services import import_service, realized
from taxfolio.services.dividends import load_dividends
from taxfolio.services.tax_cz import build_cz_report
from taxfolio.services.tax_sk import build_sk_report
from taxfolio.tax.cz import EXEMPT_LIMIT, EXEMPT_TIME_TEST

DATA = Path(__file__).parent.parent / "test_data"
EXPECTED = json.loads((DATA / "expected_cz.json").read_text(encoding="utf-8"))
D = Decimal
CENT = D("0.01")


@pytest.fixture
def portfolio(engine: Engine) -> Engine:
    for year in range(2021, 2026):
        import_service.import_file(engine, DATA / f"flex_{year}.xml")
    return engine


def test_fifo_matches_generator_and_ibkr_lots(portfolio: Engine) -> None:
    fifo = realized.compute_fifo(portfolio)
    assert realized.check_against_ibkr(portfolio, fifo) == []
    ours = {
        (m.symbol, m.close_datetime.date().isoformat(), m.open_datetime.date().isoformat()): m
        for m in fifo.result.matches
    }
    for year, data in EXPECTED.items():
        for sale in data["sales"]:
            m = ours[(sale["symbol"], sale["sold"], sale["bought"])]
            assert m.quantity == D(sale["quantity"]), sale
            assert m.pnl.quantize(CENT) == D(sale["result"]).quantize(CENT), (year, sale)


def test_2024_small_sale_exempt_by_limit(portfolio: Engine) -> None:
    report, _calendar = build_cz_report(portfolio, 2024, CzkMethod.CNB_DAILY)
    (sale,) = report.sales
    assert sale.exempt_reason == EXEMPT_LIMIT  # bought 2022 (< 3 years), but 15 000 Kč ≤ 100 000 Kč
    assert report.securities.partial_base == 0 and report.tax_total == 0


def test_2025_czech_tax(portfolio: Engine) -> None:
    report, _calendar = build_cz_report(portfolio, 2025, CzkMethod.CNB_DAILY)
    s = report.securities
    exp = EXPECTED["2025"]
    assert not s.limit_applies
    reasons = {
        (line.row.match.symbol, line.row.match.open_datetime.year): line.exempt_reason
        for line in report.sales
    }
    for sale in exp["sales"]:
        key = (sale["symbol"], int(sale["bought"][:4]))
        assert (reasons[key] == EXEMPT_TIME_TEST) == sale["cz_time_test_passed"], sale
    usd_income = (D(800) + D(5000)) * 22  # GAMR 10 × 80, ZETM 1000 × 5
    usd_expenses = (D(501) + D(2001)) * 22 + D(2) * 22  # buy cost incl. fee + sell fees
    assert s.time_test_income == D(exp["czk_exempt_time_test_income"])
    assert s.taxable_income == D(exp["czk_taxable_income"]) + usd_income
    assert s.taxable_expenses.quantize(CENT) == (D(exp["czk_taxable_expenses"]) + usd_expenses).quantize(CENT)
    base = s.partial_base
    assert base.quantize(CENT) == D("121570.33")
    # dividends: CZ out of the return; US 440 Kč with full credit 66; DE 2 420 Kč, credit only 15 % = 363
    by = {d.country: d for d in report.dividends}
    assert by["CZ"].domestic and by["CZ"].tax_due == 0
    assert by["US"].gross == 440 and by["US"].credit == 66
    assert by["DE"].gross == D("2420") and by["DE"].credit == D("363")
    assert report.tax_total.quantize(CENT) == ((base + 440 + 2420) * D("0.15") - 66 - 363).quantize(CENT)
    assert any("35%" in w for w in report.warnings) and any("DE" in w for w in report.warnings)


def test_2025_slovak_tax(portfolio: Engine) -> None:
    report, _calendar = build_sk_report(portfolio, 2025)
    taxable = sorted(line.row.match.symbol for line in report.sales if line.taxable)
    # ZETM: > 1 year but OTC (not a regulated market); EPSI: < 1 year. All others exempt.
    assert taxable == ["EPSI", "ZETM"]
    zetm = D(5000) / D("1.1") - D(2001) / D("1.1") - D(1) / D("1.1")
    epsi = D(16000) / D("24.2") - D(10050) / D("24.2") - D(50) / D("24.2")
    s = report.securities
    assert abs(s.base - (zetm + epsi - 500)) < CENT
    assert any("ZETM" in w for w in report.warnings)


def test_dividends_pair_with_withholding(portfolio: Engine) -> None:
    events, warnings = load_dividends(portfolio, None, 2025)
    assert warnings == []
    rates = {e.symbol: e.withholding_rate.quantize(D("0.001")) for e in events}
    assert rates == {"BRIZ": D("0.350"), "GAMR": D("0.150"), "DLCH": D("0.264")}


# ------------------------------------------------------------------ second account: XTB (EUR)

XTB_ID = "XTB-51234567"
EUR = D("24.2")  # flat test rate, CZK per EUR


@pytest.fixture
def two_accounts(portfolio: Engine) -> Engine:
    import_service.import_file(portfolio, DATA / "xtb_51234567_cash_operations.csv")
    return portfolio


def test_xtb_account_is_imported_next_to_ibkr(two_accounts: Engine) -> None:
    from taxfolio.services import queries

    accounts = {a: ccy for a, _name, ccy in queries.list_accounts(two_accounts)}
    assert accounts == {"U9999001": "CZK", XTB_ID: "EUR"}
    fifo = realized.compute_fifo(two_accounts, XTB_ID)
    pnl = {m.symbol: m.pnl for m in fifo.result.matches}
    # MSFT: 1 850 − 1 170 − 3.70 commission; CEZ: short-term; SAP: half of the position
    assert pnl == {"SAP.DE": D(300), "MSFT.US": D("676.30"), "CEZ.CZ": D(80)}


def test_czech_limit_counts_all_accounts(two_accounts: Engine) -> None:
    # 2024: IBKR 15 000 + XTB 900 € = 36 780 Kč ≤ 100 000 → still exempt by the limit
    r2024, _ = build_cz_report(two_accounts, 2024, CzkMethod.CNB_DAILY)
    assert r2024.securities.gross_income == 15000 + 900 * EUR and r2024.securities.limit_applies

    # 2025: XTB alone (66 066 Kč) would be under the limit – but the limit is per person
    xtb_only, _ = build_cz_report(two_accounts, 2025, CzkMethod.CNB_DAILY, XTB_ID)
    assert xtb_only.securities.limit_applies
    assert any("Všechny účty" in w for w in xtb_only.warnings)
    both, _ = build_cz_report(two_accounts, 2025, CzkMethod.CNB_DAILY)
    assert not both.securities.limit_applies and not any("Všechny účty" in w for w in both.warnings)
    xtb_gain = (D("676.30") + D(80)) * EUR
    assert both.securities.partial_base.quantize(CENT) == (D("121570.33") + xtb_gain).quantize(CENT)


def test_slovak_exemption_shared_by_accounts(two_accounts: Engine) -> None:
    report, _ = build_sk_report(two_accounts, 2025)
    taxable = sorted(line.row.match.symbol for line in report.sales if line.taxable)
    assert taxable == ["CEZ.CZ", "EPSI", "ZETM"]  # CEZ held < 1 year; MSFT > 1 year on XTB:US → exempt
    zetm = D(5000) / D("1.1") - D(2001) / D("1.1") - D(1) / D("1.1")
    epsi = D(16000) / D("24.2") - D(10050) / D("24.2") - D(50) / D("24.2")
    assert abs(report.securities.base - (zetm + epsi + 80 - 500)) < CENT  # one 500 € for both


def test_xtb_dividends_and_country_guess(two_accounts: Engine) -> None:
    events, _ = load_dividends(two_accounts, XTB_ID, 2024)
    by = {e.symbol: e for e in events}
    assert by["SAP.DE"].country == "DE" and by["SAP.DE"].withheld == D("5.8")
    assert by["MSFT.US"].country == "US" and by["MSFT.US"].withheld == D("0.51")
    # the Irish ETF is guessed as German from the listing – the import warns about it
    assert by["IUSA.DE"].country == "DE" and by["IUSA.DE"].withheld == 0


def test_overview_all_accounts_shows_withdrawal(two_accounts: Engine) -> None:
    from taxfolio.services.overview import build_overview

    ov = build_overview(two_accounts, None, "CZK")
    assert ov.deposits == 300_000 + 5000 * EUR and ov.withdrawals == -500 * EUR
    assert dict(ov.monthly_withdrawals)["Q3/25"] == -500 * EUR
    xtb = build_overview(two_accounts, None, "EUR", XTB_ID)
    assert xtb.deposits == 5000 and xtb.withdrawals == -500
    assert xtb.monthly_pnl[0][0] == "Q1/23"  # 29 months of activity → quarters
    names = {c.symbol: c.name for c in xtb.dividends_by_company}
    assert names["MSFT.US"] == "Microsoft Corp"  # XTB has no ISIN: name looked up by symbol


def test_tax_free_positions_today(portfolio: Engine) -> None:
    from datetime import date

    from taxfolio.services.tax_free import cz_tax_free, sk_tax_free

    today = date(2025, 10, 1)  # after the last trade of the test portfolio
    cz = {p.symbol: p for p in cz_tax_free(portfolio, today=today)}
    # > 3 years: all 2021 purchases still held and 2022 ones bought before 1 Oct 2022
    assert {"BRIZ", "JASM", "BOBR", "SOVA", "DLCH"} <= set(cz)
    # TRAM bought 18 Oct 2022; ALFA has only the 25 shares from Dec 2022 left (E1 sold the rest)
    assert not {"TRAM", "ALFA"} & set(cz)
    briz = cz["BRIZ"]
    assert briz.quantity == briz.held == 50 and briz.cost == 50 * 180 + 50
    assert briz.price is not None and briz.gain == briz.value - briz.cost  # type: ignore[operator]
    sk = {p.symbol: p for p in sk_tax_free(portfolio, today=today)}
    # SK: > 1 year on a regulated market – also TRAM and ALFA
    assert {"TRAM", "ALFA", "BOBR"} <= set(sk)


def test_tax_free_part_of_a_position() -> None:
    from datetime import date, datetime

    from taxfolio.engine.lots import Lot
    from taxfolio.services.tax_free import CalendarLot, tax_free_positions

    def lot(day: str, qty: int, cost: int) -> Lot:
        return Lot("K", "ABC", "CZK", 1, datetime.fromisoformat(day), D(qty), D(cost))

    calendar = [
        CalendarLot(lot("2021-01-10", 10, 1000), "ABC AS", date(2024, 1, 11)),
        CalendarLot(lot("2021-06-10", 5, 600), "ABC AS", date(2024, 6, 11)),
        CalendarLot(lot("2023-03-01", 20, 3000), "ABC AS", date(2026, 3, 2)),
        CalendarLot(lot("2023-04-01", 7, 900), "ABC AS", date(2026, 3, 2)),
    ]
    (p,) = tax_free_positions(calendar, {"K": (date(2025, 12, 31), D(150))}, date(2025, 10, 1))
    assert (p.quantity, p.held, p.exempt_since, p.cost) == (15, 42, date(2024, 6, 11), 1600)
    assert p.partial and p.value == 15 * 150 and p.gain == 2250 - 1600
    assert (p.next_date, p.next_quantity) == (date(2026, 3, 2), 27)
    # SK: a lot outside a regulated market never becomes tax-free
    assert tax_free_positions([CalendarLot(lot("2020-01-01", 1, 1), "", date(2021, 1, 2), False)]) == []

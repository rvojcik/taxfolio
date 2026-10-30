from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from taxfolio.domain.models import AssetClass, CashType
from taxfolio.importers.detect import UnsupportedFormatError, parse_file


def test_activity_statement(fixtures: Path) -> None:
    r = parse_file(fixtures / "activity_2025.csv")
    assert r.account.account_id == "U0000001"
    assert r.account.base_currency == "EUR"
    assert (r.period_start, r.period_end) == (date(2025, 1, 1), date(2025, 12, 31))

    stocks = [t for t in r.trades if t.asset_class is AssetClass.STOCK]
    fx = [t for t in r.trades if t.asset_class is AssetClass.FOREX]
    assert len(stocks) == 3 and len(fx) == 2  # SubTotal/Total rows skipped
    sell = stocks[1]
    assert sell.quantity == Decimal(-2) and sell.is_close and not sell.is_open
    assert sell.realized_pnl == Decimal("19.719908")
    assert stocks[2].codes == ("IA", "O")
    # Forex commission is reported in base currency, stock commission in trade currency
    assert fx[1].commission_currency == "EUR" and stocks[0].commission_currency == "USD"
    assert fx[0].codes == ("AFx",)


def test_activity_statement_cash_and_other_sections(fixtures: Path) -> None:
    r = parse_file(fixtures / "activity_2025.csv")
    by_type = {c.type: c for c in r.cash}
    assert set(by_type) == {
        CashType.DEPOSIT,
        CashType.WITHDRAWAL,
        CashType.FEE,
        CashType.DIVIDEND,
        CashType.WITHHOLDING_TAX,
    }
    div = by_type[CashType.DIVIDEND]
    assert (div.symbol, div.isin, div.amount) == ("COST", "US22160K1051", Decimal("1.16"))
    assert by_type[CashType.WITHDRAWAL].amount == Decimal(-500)
    assert len(r.corporate_actions) == 1 and r.corporate_actions[0].isin == "US67066G1040"
    assert len(r.open_positions) == 1 and r.open_positions[0].as_of == date(2025, 12, 31)


def test_instrument_symbol_aliases(fixtures: Path) -> None:
    r = parse_file(fixtures / "activity_2025.csv")
    exsa = next(i for i in r.instruments if i.isin == "DE0002635307")
    assert exsa.symbol == "EXSA" and exsa.aliases == ("EXSAd",)
    assert exsa.issuer_country == "DE"


def test_dividend_report(fixtures: Path) -> None:
    r = parse_file(fixtures / "dividends_2025.csv")
    assert len(r.dividend_details) == 1  # only RevenueComponent rows
    d = r.dividend_details[0]
    assert (d.country, d.conid, d.gross, d.withhold) == ("US", "272997", Decimal("1.16"), Decimal("-0.174"))


def test_fx_worksheet(fixtures: Path) -> None:
    r = parse_file(fixtures / "fx_2025.csv")
    assert [line.income for line in r.fx_income] == [Decimal("41.63"), Decimal("-0.05")]
    assert r.fx_income[0].proceeds == Decimal("1012.50")
    assert r.fx_income[0].date_acquired == date(2025, 1, 2)


def test_unknown_format(tmp_path: Path) -> None:
    p = tmp_path / "x.csv"
    p.write_text("a,b,c\n1,2,3\n")
    with pytest.raises(UnsupportedFormatError):
        parse_file(p)

"""XTB cash operations importer. All rows are invented, in the layouts of real XTB exports."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import Engine

from taxfolio.domain.models import CashType
from taxfolio.importers import xtb
from taxfolio.importers.detect import parse_file
from taxfolio.services import import_service
from taxfolio.services.dividends import load_dividends

D = Decimal

LEGACY = """ID;Type;Time;Symbol;Comment;Amount
1005;Stocks/ETF sale;02.04.2024 11:42:37;ZAL.DE;CLOSE BUY 1 @ 26.280;26.28
1004;Stocks/ETF purchase;02.04.2024 10:21:47;ZAL.DE;OPEN BUY 1 @ 26.400;-26.4
1003;Stocks/ETF purchase;12.04.2024 13:01:45;SPYL.DE;OPEN BUY 34/42.5658 @ 11.7480;-399.43
1002;Stocks/ETF purchase;12.04.2024 13:01:44;SPYL.DE;OPEN BUY 8.5658/42.5658 @ 11.7470;-100.62
1006;Stocks/ETF purchase;15.05.2024 16:00:00;AAPL.US;OPEN BUY 2 @ 190.00;-352.10
1007;Dividend;16.05.2024 11:00:23;AAPL.US;AAPL.US USD 0.2500/ SHR;0.46
1008;Withholding tax;16.05.2024 11:00:23;AAPL.US;AAPL.US USD WHT 15%;-0.07
1009;Deposit;27.03.2024 09:00:21;;JP_MORGAN deposit, id=1;1400
1010;Free funds interests;05.04.2024 13:42:58;;Free-funds Interest 2024-03;0.1
1011;Free funds interests tax;05.04.2024 13:42:58;;Free-funds Interest Tax 2024-03;-0.02
1012;Profit/Loss (FX/CFD);22.07.2024 01:35:43;EURUSD;Profit of position #685669464;0.13
1013;Dividend;05.11.2024 22:00:01;US30.cash;US30.cash USD 6.5000/ Indices;-0.05
1004;Stocks/ETF purchase;02.04.2024 10:21:47;ZAL.DE;OPEN BUY 1 @ 26.400;-26.4
"""

CURRENT = """Account number;51234567
Currency;CZK
Date from (UTC);2025-01-01 00:00:00
Date to (UTC);2025-12-31 23:59:59
Type;Ticker;Instrument;Time;Amount;ID;Comment;Product
Stock purchase;CEZ.CZ;CEZ;2025-01-03 10:00:00;-10 500,00;2001;OPEN BUY 10 @ 1050.00;My Trades
Commission;CEZ.CZ;CEZ;2025-01-03 10:00:00;-52,50;2002;Commission;My Trades
Stock sale;CEZ.CZ;CEZ;2025-06-03 10:00:00;12 000,00;2003;CLOSE BUY 10 @ 1200.00;My Trades
Dividend;MSFT.US;Microsoft Corp;2025-03-14 11:00:00;150,30;2004;MSFT.US USD 0.8300/ SHR;My Trades
Withholding tax;MSFT.US;Microsoft Corp;2025-03-14 11:00:00;-22,55;2005;MSFT.US USD WHT 15%;My Trades
Spin off;T.US;AT&T;2025-04-01 10:00:00;21,68;2006;T.US USD 5.8970/ SHR;My Trades
Total;;;;;;;
"""


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_legacy_csv(tmp_path: Path) -> None:
    parsed = parse_file(write(tmp_path, "cash_operations.csv", LEGACY))
    assert parsed.source_format == xtb.FORMAT
    # No account number in the file, currency from the trades priced in EUR
    assert parsed.account.account_id == "XTB-EUR" and parsed.account.base_currency == "EUR"

    trades = {(t.symbol, t.trade_datetime): t for t in parsed.trades}
    assert len(parsed.trades) == 5  # the repeated row 1004 is dropped
    sale = trades[("ZAL.DE", datetime(2024, 4, 2, 11, 42, 37))]
    assert sale.quantity == -1 and sale.proceeds == D("26.28") and sale.is_close
    part = trades[("SPYL.DE", datetime(2024, 4, 12, 13, 1, 45))]
    assert part.quantity == 34 and part.proceeds == D("-399.43") and part.is_open
    apple = trades[("AAPL.US", datetime(2024, 5, 15, 16))]
    # Amount is in the account currency (EUR) although the price in the comment is in USD
    assert apple.currency == "EUR" and apple.price == D("176.05")

    kinds = [(c.type, c.symbol, c.amount) for c in parsed.cash]
    assert (CashType.DIVIDEND, "AAPL.US", D("0.46")) in kinds
    assert (CashType.WITHHOLDING_TAX, "AAPL.US", D("-0.07")) in kinds
    assert (CashType.INTEREST, None, D("0.1")) in kinds
    assert (CashType.WITHHOLDING_TAX, None, D("-0.02")) in kinds
    assert (CashType.DEPOSIT, None, D("1400")) in kinds
    assert not any(c.symbol == "US30.cash" for c in parsed.cash)  # index CFD adjustment
    assert any("CFD" in w for w in parsed.warnings)

    countries = {i.symbol: i.issuer_country for i in parsed.instruments}
    assert countries == {"AAPL.US": "US", "SPYL.DE": "DE", "ZAL.DE": "DE"}


def test_current_export_with_metadata_commission_and_decimal_comma(tmp_path: Path) -> None:
    parsed = parse_file(write(tmp_path, "account_51234567_cash.csv", CURRENT))
    assert parsed.account.account_id == "XTB-51234567" and parsed.account.base_currency == "CZK"
    buy, sale = sorted(parsed.trades, key=lambda t: t.trade_datetime)
    assert buy.proceeds == D("-10500.00") and buy.commission == D("-52.50")  # commission joined
    assert sale.quantity == -10 and sale.proceeds == D("12000.00")
    assert not any(c.type == CashType.FEE for c in parsed.cash)
    assert {i.symbol: i.description for i in parsed.instruments}["MSFT.US"] == "Microsoft Corp"
    assert any("Spin off" in w for w in parsed.warnings)
    assert parsed.period_start == date(2025, 1, 3) and parsed.period_end == date(2025, 6, 3)


def test_comma_separated_variant(tmp_path: Path) -> None:
    text = CURRENT.replace(";", ",").replace("-10 500,00", '"-10,500.00"').replace("-52,50", "-52.50")
    text = text.replace("12 000,00", "12000.00").replace("150,30", "150.30").replace("-22,55", "-22.55")
    text = text.replace("21,68", "21.68")
    parsed = parse_file(write(tmp_path, "cash.csv", text))
    assert sorted(t.proceeds for t in parsed.trades) == [D("-10500.00"), D("12000.00")]


def test_excel_statement(tmp_path: Path) -> None:
    wb = Workbook()
    wb.active.title = "Closed Positions"
    ws = wb.create_sheet("Cash Operations")
    ws.append(["Account number", 51234567])
    ws.append(["Currency", "USD"])
    ws.append([])
    ws.append(["Type", "Ticker", "Instrument", "Time", "Amount", "ID", "Comment", "Product"])
    ws.append(
        [
            "Stock purchase",
            "MSFT.US",
            "Microsoft",
            datetime(2025, 2, 3, 15, 30),
            -823.05,
            3001,
            "OPEN BUY 2 @ 411.525",
            "x",
        ]
    )
    ws.append(["Total", None, None, None, -823.05])
    path = tmp_path / "statement.xlsx"
    wb.save(path)

    parsed = parse_file(path)
    assert parsed.account.account_id == "XTB-51234567"
    (t,) = parsed.trades
    assert t.proceeds == D("-823.05") and t.quantity == 2 and t.currency == "USD"


def test_unknown_currency_asks_for_file_name(tmp_path: Path) -> None:
    text = "ID;Type;Time;Symbol;Comment;Amount\n1;Deposit;02.04.2024 10:00:00;;Deposit;100\n"
    with pytest.raises(ValueError, match="EUR_cash.csv"):
        parse_file(write(tmp_path, "cash.csv", text))
    assert parse_file(write(tmp_path, "EUR_cash.csv", text)).account.base_currency == "EUR"


def test_import_dividend_with_tax_and_reimport(engine: Engine, tmp_path: Path) -> None:
    path = write(tmp_path, "account_51234567_cash.csv", CURRENT)
    first = import_service.import_file(engine, path)
    assert first.total_new > 0
    assert import_service.import_file(engine, path).total_new == 0

    events, warnings = load_dividends(engine, "XTB-51234567", 2025)
    (msft,) = events
    assert msft.country == "US" and msft.gross == D("150.30") and msft.withheld == D("22.55")
    assert warnings == []


def test_xtb_listing_counts_as_regulated_market_for_sk(engine: Engine, tmp_path: Path) -> None:
    from taxfolio.services.tax_sk import listing_exchanges
    from taxfolio.tax.rules_loader import load_sk

    import_service.import_file(engine, write(tmp_path, "account_51234567_cash.csv", CURRENT))
    exchange = listing_exchanges(engine)["SYM:CEZ.CZ"]
    assert exchange == "XTB:CZ" and exchange in load_sk(2025).regulated_exchanges

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from taxfolio.domain.models import AssetClass, CashType
from taxfolio.importers.detect import parse_file


def test_flex_statement_header(fixtures: Path) -> None:
    r = parse_file(fixtures / "flex_2025.xml")
    assert r.source_format == "ibkr_flex_xml"
    assert (r.account.account_id, r.account.base_currency) == ("U0000001", "EUR")
    assert (r.period_start, r.period_end) == (date(2025, 1, 1), date(2025, 12, 31))
    assert r.warnings == []


def test_flex_keeps_executions_not_orders(fixtures: Path) -> None:
    r = parse_file(fixtures / "flex_2025.xml")
    assert [t.trade_id for t in r.trades] == ["1", "2", "3"]
    buy, sell, fx = r.trades
    assert buy.codes == ("O",) and buy.order_type == "LMT"
    assert sell.codes == ("C", "P") and sell.order_type == "STP"
    assert sell.order_time == datetime(2025, 8, 21, 1, 46, 53)
    assert sell.realized_pnl == Decimal("78.6") and sell.fx_rate_to_base == Decimal("0.9")
    assert fx.asset_class is AssetClass.FOREX and fx.codes == ("AFx",) and fx.commission_currency == "EUR"


def test_flex_closed_lots_and_positions(fixtures: Path) -> None:
    r = parse_file(fixtures / "flex_2025.xml")
    (lot,) = r.closed_lots
    assert lot.open_datetime == datetime(2025, 2, 13, 10, 57, 30)
    assert lot.quantity == Decimal(2) and lot.open_transaction_id == "9001"
    assert [p.level for p in r.open_positions] == ["SUMMARY", "LOT"]
    assert r.open_positions[1].open_datetime == datetime(2025, 2, 13, 10, 57, 30)


def test_flex_cash_and_corporate_actions(fixtures: Path) -> None:
    r = parse_file(fixtures / "flex_2025.xml")
    div, wht, dep = r.cash
    assert (div.type, div.ex_date, div.action_id) == (CashType.DIVIDEND, date(2025, 2, 7), "600")
    assert wht.type is CashType.WITHHOLDING_TAX and wht.action_id == div.action_id
    assert dep.type is CashType.DEPOSIT
    (ca,) = r.corporate_actions
    assert ca.action_type == "FS" and ca.quantity == Decimal(18)
    assert len(r.fx_rates) == 2 and r.fx_rates[0].rate == Decimal("0.95")
    assert {i.symbol: i.issuer_country for i in r.instruments} == {"AAPL": "US", "COST": "US"}


def test_flex_missing_sections_warn(tmp_path: Path) -> None:
    p = tmp_path / "empty.xml"
    p.write_text(
        '<?xml version="1.0"?>\n<FlexQueryResponse><FlexStatements count="1">'
        '<FlexStatement accountId="U1" fromDate="20250101" toDate="20251231">'
        '<AccountInformation name="X" currency="EUR"/></FlexStatement></FlexStatements></FlexQueryResponse>'
    )
    r = parse_file(p)
    assert r.trades == [] and "Trades" in r.warnings[0]

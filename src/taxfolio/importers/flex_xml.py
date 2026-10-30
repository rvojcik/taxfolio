"""Parser for IBKR Activity Flex Query XML (query ``taxfolio_full``, see README)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from taxfolio.domain.models import (
    AccountInfo,
    AssetClass,
    CashTransaction,
    CashType,
    ClosedLot,
    CorporateAction,
    FxRate,
    Instrument,
    OpenPosition,
    ParsedFile,
    Trade,
)
from taxfolio.i18n import _
from taxfolio.importers.ib_csv import parse_decimal

FORMAT = "ibkr_flex_xml"

ASSET_CLASSES = {
    "STK": AssetClass.STOCK,
    "CASH": AssetClass.FOREX,
    "BOND": AssetClass.BOND,
    "OPT": AssetClass.OPTION,
    "FUT": AssetClass.FUTURE,
}

CASH_TYPES = {
    "Dividends": CashType.DIVIDEND,
    "Payment In Lieu Of Dividends": CashType.PAYMENT_IN_LIEU,
    "Withholding Tax": CashType.WITHHOLDING_TAX,
    "Broker Interest Received": CashType.INTEREST,
    "Broker Interest Paid": CashType.INTEREST,
    "Bond Interest Received": CashType.INTEREST,
    "Bond Interest Paid": CashType.INTEREST,
    "Other Fees": CashType.FEE,
    "Commission Adjustments": CashType.FEE,
    "Deposits/Withdrawals": CashType.DEPOSIT,
}

# Sections the importer relies on; a missing one usually means it was not saved in the query.
REQUIRED_SECTIONS = ("Trades", "CashTransactions", "CorporateActions", "OpenPositions", "SecuritiesInfo")


def is_flex_xml(head: str) -> bool:
    if head.startswith("<?xml"):
        head = head[head.find("?>") + 2 :].lstrip()
    return head.startswith("<FlexQueryResponse")


def _date(text: str | None) -> date | None:
    if not text:
        return None
    return datetime.strptime(text[:8], "%Y%m%d").date()


def _dt(text: str | None) -> datetime | None:
    """Flex uses 'yyyyMMdd;HHmmss' (configured in the query) or plain 'yyyyMMdd'."""
    if not text:
        return None
    if ";" in text:
        return datetime.strptime(text, "%Y%m%d;%H%M%S")
    return datetime.strptime(text, "%Y%m%d")


def _dec(e: ET.Element, attr: str) -> Decimal:
    return parse_decimal(e.get(attr, ""))


def _opt(e: ET.Element, attr: str) -> str | None:
    return e.get(attr) or None


def _asset(e: ET.Element) -> AssetClass:
    return ASSET_CLASSES.get(e.get("assetCategory", ""), AssetClass.OTHER)


def parse(path: Path) -> ParsedFile:
    root = ET.parse(path).getroot()
    statements = root.findall("./FlexStatements/FlexStatement")
    if not statements:
        raise ValueError(_("{file}: Flex soubor neobsahuje žádný FlexStatement").format(file=path.name))
    if len(statements) > 1:
        raise ValueError(
            _("{file}: více účtů v jednom Flex souboru zatím není podporováno").format(file=path.name)
        )
    st = statements[0]

    info = st.find("AccountInformation")
    account_id = st.get("accountId", "")
    # AccountInformation also carries address, e-mail and birth date – deliberately not read.
    account = AccountInfo(
        account_id,
        info.get("name", "") if info is not None else "",
        info.get("currency", "") if info is not None else "",
    )
    result = ParsedFile(
        source_format=FORMAT,
        account=account,
        period_start=_date(st.get("fromDate")),
        period_end=_date(st.get("toDate")),
    )
    missing = [s for s in REQUIRED_SECTIONS if st.find(s) is None]
    if missing:
        result.warnings.append(
            _("Ve Flex Query chybí sekce: {sections} (zapněte je a uložte v dotazu)").format(
                sections=", ".join(missing)
            )
        )

    result.instruments = [_instrument(e) for e in st.iterfind("SecuritiesInfo/SecurityInfo")]
    for e in st.iterfind("Trades/*"):
        level = e.get("levelOfDetail")
        if level == "EXECUTION":
            result.trades.append(_trade(account_id, e))
        elif level == "CLOSED_LOT":
            result.closed_lots.append(_closed_lot(account_id, e))
        # ORDER rows aggregate executions; we keep executions and group by ibOrderID ourselves.
    for e in st.iterfind("CashTransactions/CashTransaction"):
        if e.get("levelOfDetail", "DETAIL") == "DETAIL":
            result.cash.append(_cash(account_id, e, result))
    result.corporate_actions = [
        _corporate_action(account_id, e)
        for e in st.iterfind("CorporateActions/CorporateAction")
        if e.get("levelOfDetail", "DETAIL") == "DETAIL"
    ]
    result.open_positions = [_open_position(account_id, e) for e in st.iterfind("OpenPositions/OpenPosition")]
    result.fx_rates = [
        FxRate(
            date=_date(e.get("reportDate")) or date.min,
            from_currency=e.get("fromCurrency", ""),
            to_currency=e.get("toCurrency", ""),
            rate=_dec(e, "rate"),
            source="IBKR",
        )
        for e in st.iterfind("ConversionRates/ConversionRate")
    ]
    return result


def _instrument(e: ET.Element) -> Instrument:
    return Instrument(
        symbol=e.get("symbol", ""),
        asset_class=_asset(e),
        description=e.get("description", ""),
        conid=_opt(e, "conid"),
        isin=_opt(e, "isin") or _opt(e, "securityID"),
        listing_exchange=_opt(e, "listingExchange"),
        instrument_type=_opt(e, "subCategory"),
        issuer_country=_opt(e, "issuerCountryCode"),
    )


def _trade(account_id: str, e: ET.Element) -> Trade:
    codes = [c for c in e.get("notes", "").split(";") if c]
    open_close = e.get("openCloseIndicator", "")
    # Activity Statements put O/C into the codes; do the same so both sources read alike.
    for flag in open_close.split(";"):
        if flag in ("O", "C") and flag not in codes:
            codes.insert(0, flag)
    trade_dt = _dt(e.get("dateTime"))
    assert trade_dt is not None
    return Trade(
        account_id=account_id,
        asset_class=_asset(e),
        symbol=e.get("symbol", ""),
        currency=e.get("currency", ""),
        trade_datetime=trade_dt,
        quantity=_dec(e, "quantity"),
        price=_dec(e, "tradePrice"),
        proceeds=_dec(e, "proceeds"),
        commission=_dec(e, "ibCommission"),
        commission_currency=e.get("ibCommissionCurrency") or e.get("currency") or "",
        basis=_dec(e, "cost"),
        realized_pnl=_dec(e, "fifoPnlRealized"),
        codes=tuple(codes),
        conid=_opt(e, "conid"),
        isin=_opt(e, "isin"),
        trade_id=_opt(e, "tradeID"),
        transaction_id=_opt(e, "transactionID"),
        order_id=_opt(e, "ibOrderID"),
        order_type=_opt(e, "orderType"),
        order_reference=_opt(e, "orderReference"),
        order_time=_dt(e.get("orderTime")),
        fx_rate_to_base=_dec(e, "fxRateToBase"),
    )


def _closed_lot(account_id: str, e: ET.Element) -> ClosedLot:
    close_dt, open_dt = _dt(e.get("dateTime")), _dt(e.get("openDateTime"))
    assert close_dt is not None and open_dt is not None
    return ClosedLot(
        account_id=account_id,
        asset_class=_asset(e),
        symbol=e.get("symbol", ""),
        currency=e.get("currency", ""),
        close_datetime=close_dt,
        quantity=_dec(e, "quantity"),
        open_datetime=open_dt,
        cost=_dec(e, "cost"),
        realized_pnl=_dec(e, "fifoPnlRealized"),
        conid=_opt(e, "conid"),
        isin=_opt(e, "isin"),
        open_transaction_id=_opt(e, "transactionID"),
    )


def _cash(account_id: str, e: ET.Element, result: ParsedFile) -> CashTransaction:
    raw_type = e.get("type", "")
    cash_type = CASH_TYPES.get(raw_type)
    if cash_type is None:
        result.warnings.append(
            _("Neznámý typ peněžní transakce '{kind}' – uloženo jako OTHER").format(kind=raw_type)
        )
        cash_type = CashType.OTHER
    amount = _dec(e, "amount")
    if cash_type is CashType.DEPOSIT and amount < 0:
        cash_type = CashType.WITHDRAWAL
    when = _date(e.get("dateTime")) or _date(e.get("settleDate"))
    assert when is not None
    return CashTransaction(
        account_id=account_id,
        type=cash_type,
        currency=e.get("currency", ""),
        date=when,
        amount=amount,
        description=e.get("description", ""),
        symbol=_opt(e, "symbol"),
        isin=_opt(e, "isin"),
        code=e.get("code", ""),
        conid=_opt(e, "conid"),
        ex_date=_date(e.get("exDate")),
        action_id=_opt(e, "actionID"),
        transaction_id=_opt(e, "transactionID"),
        fx_rate_to_base=_dec(e, "fxRateToBase"),
    )


def _corporate_action(account_id: str, e: ET.Element) -> CorporateAction:
    report = _date(e.get("reportDate"))
    when = _dt(e.get("dateTime"))
    assert report is not None and when is not None
    return CorporateAction(
        account_id=account_id,
        currency=e.get("currency", ""),
        report_date=report,
        action_datetime=when,
        description=e.get("actionDescription", "") or e.get("description", ""),
        quantity=_dec(e, "quantity"),
        proceeds=_dec(e, "proceeds"),
        value=_dec(e, "value"),
        symbol=_opt(e, "symbol"),
        isin=_opt(e, "isin"),
        conid=_opt(e, "conid"),
        action_type=_opt(e, "type"),
        action_id=_opt(e, "actionID"),
        transaction_id=_opt(e, "transactionID"),
    )


def _open_position(account_id: str, e: ET.Element) -> OpenPosition:
    as_of = _date(e.get("reportDate"))
    assert as_of is not None
    return OpenPosition(
        account_id=account_id,
        as_of=as_of,
        asset_class=_asset(e),
        symbol=e.get("symbol", ""),
        currency=e.get("currency", ""),
        quantity=_dec(e, "position"),
        cost_basis=_dec(e, "costBasisMoney"),
        close_price=_dec(e, "markPrice"),
        value=_dec(e, "positionValue"),
        unrealized_pnl=_dec(e, "fifoPnlUnrealized"),
        conid=_opt(e, "conid"),
        isin=_opt(e, "isin"),
        level=e.get("levelOfDetail", "SUMMARY"),
        open_datetime=_dt(e.get("openDateTime")),
    )

"""Parser for the IBKR Activity Statement CSV (Reports → Statements → Activity, format CSV)."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from taxfolio.domain.models import (
    AccountInfo,
    AssetClass,
    CashTransaction,
    CashType,
    CorporateAction,
    Instrument,
    OpenPosition,
    ParsedFile,
    Trade,
)
from taxfolio.i18n import _
from taxfolio.importers.ib_csv import (
    Row,
    iter_data,
    parse_date,
    parse_datetime,
    parse_decimal,
    parse_optional_decimal,
    read_sections,
)

FORMAT = "ibkr_activity_statement_csv"

ASSET_CATEGORIES = {
    "Stocks": AssetClass.STOCK,
    "Forex": AssetClass.FOREX,
    "Bonds": AssetClass.BOND,
    "Equity and Index Options": AssetClass.OPTION,
    "Futures": AssetClass.FUTURE,
}

# "CEZ(CZ0005112300) Cash Dividend CZK 47.00 per Share (Ordinary Dividend)"
_SYMBOL_ISIN = re.compile(r"^(?P<symbol>[^\s(]+)\s*\((?P<isin>[A-Z]{2}[A-Z0-9]{9}[0-9])\)")

# Section name → cash type; sign of the amount decides deposit vs withdrawal.
_CASH_SECTIONS = {
    "Dividends": CashType.DIVIDEND,
    "Payment In Lieu Of Dividends": CashType.PAYMENT_IN_LIEU,
    "Withholding Tax": CashType.WITHHOLDING_TAX,
    "Interest": CashType.INTEREST,
    "Fees": CashType.FEE,
    "Deposits & Withdrawals": CashType.DEPOSIT,
}


def is_activity_statement(head: str) -> bool:
    return head.startswith("Statement,Header,Field Name,Field Value")


def parse(path: Path) -> ParsedFile:
    sections = read_sections(path)
    statement = _field_map(sections.get("Statement", []))
    info = _field_map(sections.get("Account Information", []))
    if statement.get("Title") != "Activity Statement":
        raise ValueError(f"{path.name}: not an IBKR Activity Statement")
    account_id = info.get("Account", "")
    if not account_id:
        raise ValueError(f"{path.name}: missing account number in 'Account Information'")

    result = ParsedFile(
        source_format=FORMAT,
        account=AccountInfo(account_id, info.get("Name", ""), info.get("Base Currency", "")),
    )
    result.period_start, result.period_end = _parse_period(statement.get("Period", ""))

    result.instruments = _instruments(sections.get("Financial Instrument Information", []))
    result.trades = _trades(account_id, result.account.base_currency, sections.get("Trades", []), result)
    for section, cash_type in _CASH_SECTIONS.items():
        result.cash.extend(_cash(account_id, cash_type, sections.get(section, [])))
    result.corporate_actions = _corporate_actions(account_id, sections.get("Corporate Actions", []))
    if result.period_end:
        result.open_positions = _open_positions(
            account_id, result.period_end, sections.get("Open Positions", [])
        )
    return result


def _field_map(rows: list[Row]) -> dict[str, str]:
    return {r.get("Field Name"): r.get("Field Value") for r in iter_data(rows)}


def _parse_period(text: str) -> tuple[date | None, date | None]:
    # "January 1, 2025 - December 31, 2025"; single-day statements have no " - ".
    parts = [p.strip() for p in text.split(" - ")] if text else []
    try:
        dates = [datetime.strptime(p, "%B %d, %Y").date() for p in parts]
    except ValueError:
        return None, None
    if not dates:
        return None, None
    return dates[0], dates[-1]


def _asset_class(category: str) -> AssetClass:
    return ASSET_CATEGORIES.get(category, AssetClass.OTHER)


def _split_symbol_isin(description: str) -> tuple[str | None, str | None]:
    m = _SYMBOL_ISIN.match(description.strip())
    return (m.group("symbol"), m.group("isin")) if m else (None, None)


def _instruments(rows: list[Row]) -> list[Instrument]:
    out = []
    for r in iter_data(rows):
        isin = r.get("Security ID") or None
        # "EXSA, EXSAd": several symbols for one contract
        symbol, *aliases = [s.strip() for s in r.get("Symbol").split(",") if s.strip()]
        out.append(
            Instrument(
                symbol=symbol,
                aliases=tuple(aliases),
                asset_class=_asset_class(r.get("Asset Category")),
                description=r.get("Description"),
                conid=r.get("Conid") or None,
                isin=isin,
                listing_exchange=r.get("Listing Exch") or None,
                instrument_type=r.get("Type") or None,
                # Fallback only; the Dividend Report carries IBKR's own country attribution.
                issuer_country=isin[:2] if isin else None,
            )
        )
    return out


def _trades(account_id: str, base_ccy: str, rows: list[Row], result: ParsedFile) -> list[Trade]:
    out = []
    skipped_lots = 0
    for r in iter_data(rows):
        discriminator = r.get("DataDiscriminator")
        if discriminator == "ClosedLot":
            skipped_lots += 1
            continue
        if discriminator not in ("Order", "Trade", "Execution"):
            continue
        # Stocks report "Comm/Fee" in trade currency, forex reports "Comm in <BASE>".
        comm_key = next((k for k in r.values if k.startswith("Comm")), "Comm/Fee")
        comm_ccy = comm_key.removeprefix("Comm in ").strip() if comm_key.startswith("Comm in ") else None
        currency = r.get("Currency")
        out.append(
            Trade(
                account_id=account_id,
                asset_class=_asset_class(r.get("Asset Category")),
                symbol=r.get("Symbol"),
                currency=currency,
                trade_datetime=parse_datetime(r.get("Date/Time")),
                quantity=parse_decimal(r.get("Quantity")),
                price=parse_decimal(r.get("T. Price")),
                proceeds=parse_decimal(r.get("Proceeds")),
                commission=parse_decimal(r.get(comm_key)),
                commission_currency=comm_ccy or currency or base_ccy,
                basis=parse_optional_decimal(r.get("Basis")),
                realized_pnl=parse_optional_decimal(r.get("Realized P/L")),
                codes=tuple(c for c in r.get("Code").split(";") if c),
            )
        )
    if skipped_lots:
        result.warnings.append(
            _("Trades: {count} řádků ClosedLot zatím ignorováno").format(count=skipped_lots)
        )
    return out


def _cash(account_id: str, cash_type: CashType, rows: list[Row]) -> list[CashTransaction]:
    out = []
    for r in iter_data(rows):
        currency = r.get("Currency")
        raw_date = r.get("Date") or r.get("Settle Date")
        if not raw_date or currency.startswith("Total") or r.get("Subtitle").startswith("Total"):
            continue
        amount = parse_decimal(r.get("Amount"))
        description = r.get("Description")
        kind = cash_type
        if cash_type is CashType.DEPOSIT and amount < 0:
            kind = CashType.WITHDRAWAL
        symbol, isin = _split_symbol_isin(description)
        out.append(
            CashTransaction(
                account_id=account_id,
                type=kind,
                currency=currency,
                date=parse_date(raw_date),
                amount=amount,
                description=description,
                symbol=symbol,
                isin=isin,
                code=r.get("Code"),
            )
        )
    return out


def _corporate_actions(account_id: str, rows: list[Row]) -> list[CorporateAction]:
    out = []
    for r in iter_data(rows):
        if r.get("Asset Category").startswith("Total") or not r.get("Date/Time"):
            continue
        symbol, isin = _split_symbol_isin(r.get("Description"))
        out.append(
            CorporateAction(
                account_id=account_id,
                currency=r.get("Currency"),
                report_date=parse_date(r.get("Report Date")),
                action_datetime=parse_datetime(r.get("Date/Time")),
                description=r.get("Description"),
                quantity=parse_decimal(r.get("Quantity")),
                proceeds=parse_decimal(r.get("Proceeds")),
                value=parse_decimal(r.get("Value")),
                symbol=symbol,
                isin=isin,
            )
        )
    return out


def _open_positions(account_id: str, as_of: date, rows: list[Row]) -> list[OpenPosition]:
    out = []
    for r in iter_data(rows):
        if r.get("DataDiscriminator") != "Summary":
            continue
        out.append(
            OpenPosition(
                account_id=account_id,
                as_of=as_of,
                asset_class=_asset_class(r.get("Asset Category")),
                symbol=r.get("Symbol"),
                currency=r.get("Currency"),
                quantity=parse_decimal(r.get("Quantity")),
                cost_basis=parse_decimal(r.get("Cost Basis")),
                close_price=parse_decimal(r.get("Close Price")),
                value=parse_decimal(r.get("Value")),
                unrealized_pnl=parse_decimal(r.get("Unrealized P/L")),
            )
        )
    return out

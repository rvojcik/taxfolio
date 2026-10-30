"""Broker-independent domain records produced by importers and stored in the database.

All monetary values are ``Decimal``. Datetimes from IBKR statements are naive and expressed
in US/Eastern time (IBKR reporting time zone); dates are what matter for tax purposes.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class AssetClass(StrEnum):
    STOCK = "STK"
    FOREX = "CASH"
    BOND = "BOND"
    OPTION = "OPT"
    FUTURE = "FUT"
    OTHER = "OTHER"


class CashType(StrEnum):
    DIVIDEND = "DIVIDEND"
    PAYMENT_IN_LIEU = "PAYMENT_IN_LIEU"
    WITHHOLDING_TAX = "WITHHOLDING_TAX"
    INTEREST = "INTEREST"
    FEE = "FEE"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    OTHER = "OTHER"


@dataclass(frozen=True)
class AccountInfo:
    account_id: str
    name: str
    base_currency: str


@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset_class: AssetClass
    description: str = ""
    conid: str | None = None
    isin: str | None = None
    listing_exchange: str | None = None
    instrument_type: str | None = None  # COMMON, ETF, ...
    issuer_country: str | None = None
    # Other symbols IBKR uses for the same contract, e.g. ("EXSAd",) for EXSA
    aliases: tuple[str, ...] = ()

    @property
    def all_symbols(self) -> tuple[str, ...]:
        return (self.symbol, *self.aliases)


@dataclass(frozen=True)
class Trade:
    account_id: str
    asset_class: AssetClass
    symbol: str
    currency: str
    trade_datetime: datetime
    quantity: Decimal
    price: Decimal
    proceeds: Decimal
    commission: Decimal
    commission_currency: str
    basis: Decimal | None = None
    realized_pnl: Decimal | None = None
    codes: tuple[str, ...] = ()
    conid: str | None = None
    isin: str | None = None
    # Only available from Flex Queries
    trade_id: str | None = None
    transaction_id: str | None = None
    order_id: str | None = None
    order_type: str | None = None  # LMT, MKT, STP, TRAIL, ...
    order_reference: str | None = None
    order_time: datetime | None = None
    fx_rate_to_base: Decimal | None = None

    @property
    def is_open(self) -> bool:
        return "O" in self.codes

    @property
    def is_close(self) -> bool:
        return "C" in self.codes


@dataclass(frozen=True)
class CashTransaction:
    account_id: str
    type: CashType
    currency: str
    date: date
    amount: Decimal
    description: str
    symbol: str | None = None
    isin: str | None = None
    code: str = ""
    conid: str | None = None
    ex_date: dt.date | None = None  # dt.: the field 'date' shadows the type here
    # Links a dividend to its withholding tax and later corrections (Flex only)
    action_id: str | None = None
    transaction_id: str | None = None
    fx_rate_to_base: Decimal | None = None


@dataclass(frozen=True)
class CorporateAction:
    account_id: str
    currency: str
    report_date: date
    action_datetime: datetime
    description: str
    quantity: Decimal
    proceeds: Decimal
    value: Decimal
    symbol: str | None = None
    isin: str | None = None
    conid: str | None = None
    action_type: str | None = None  # FS forward split, RS reverse split, ... (Flex only)
    action_id: str | None = None
    transaction_id: str | None = None


@dataclass(frozen=True)
class OpenPosition:
    account_id: str
    as_of: date
    asset_class: AssetClass
    symbol: str
    currency: str
    quantity: Decimal
    cost_basis: Decimal
    close_price: Decimal
    value: Decimal
    unrealized_pnl: Decimal
    conid: str | None = None
    isin: str | None = None
    # SUMMARY = whole position, LOT = one purchase lot (Flex only, carries open_datetime)
    level: str = "SUMMARY"
    open_datetime: datetime | None = None


@dataclass(frozen=True)
class ClosedLot:
    """Purchase lot consumed by a closing trade, as matched by IBKR (Flex 'Closed Lots')."""

    account_id: str
    asset_class: AssetClass
    symbol: str
    currency: str
    close_datetime: datetime
    quantity: Decimal
    open_datetime: datetime
    cost: Decimal
    realized_pnl: Decimal
    conid: str | None = None
    isin: str | None = None
    open_transaction_id: str | None = None


@dataclass(frozen=True)
class FxRate:
    date: date
    from_currency: str
    to_currency: str
    rate: Decimal
    source: str


@dataclass(frozen=True)
class DividendDetail:
    """One line of the IBKR Dividend Report (carries the source country)."""

    account_id: str
    currency: str
    symbol: str
    conid: str
    country: str
    report_date: date
    ex_date: date | None
    gross: Decimal
    gross_in_base: Decimal
    withhold: Decimal
    withhold_in_base: Decimal
    revenue_component: str = ""


@dataclass(frozen=True)
class FxIncomeLine:
    """One line of the IBKR FX Income Worksheet (P/L on currency positions in base currency)."""

    account_id: str
    year: int
    currency: str
    description: str
    date_acquired: date
    source_of_acquisition: str
    date_disposed: date
    source_of_disposition: str
    proceeds: Decimal
    cost: Decimal
    income: Decimal
    code: str = ""


@dataclass
class ParsedFile:
    """Result of parsing one input file."""

    source_format: str
    account: AccountInfo
    period_start: date | None = None
    period_end: date | None = None
    instruments: list[Instrument] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    closed_lots: list[ClosedLot] = field(default_factory=list)
    cash: list[CashTransaction] = field(default_factory=list)
    corporate_actions: list[CorporateAction] = field(default_factory=list)
    open_positions: list[OpenPosition] = field(default_factory=list)
    dividend_details: list[DividendDetail] = field(default_factory=list)
    fx_income: list[FxIncomeLine] = field(default_factory=list)
    fx_rates: list[FxRate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

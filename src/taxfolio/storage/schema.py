"""SQLite schema (SQLAlchemy Core).

Every imported row has a ``natural_key`` that is unique per table, so re-importing the same file
(or overlapping periods) never creates duplicates. Activity Statements carry no trade IDs, so the
key is derived from the row content plus an occurrence counter for identical rows in one file.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    TypeDecorator,
)
from sqlalchemy.engine import Dialect

SCHEMA_VERSION = 3


class DecimalText(TypeDecorator[Decimal]):
    """Exact decimal stored as TEXT (SQLite has no decimal type)."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> str | None:
        return None if value is None else str(value)

    def process_result_value(self, value: str | None, dialect: Dialect) -> Decimal | None:
        return None if value is None else Decimal(value)


metadata = MetaData()

meta = Table(
    "meta",
    metadata,
    Column("key", String, primary_key=True),
    Column("value", String, nullable=False),
)

account = Table(
    "account",
    metadata,
    Column("account_id", String, primary_key=True),
    Column("name", String, nullable=False, default=""),
    Column("base_currency", String, nullable=False, default=""),
)

import_batch = Table(
    "import_batch",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("account_id", ForeignKey("account.account_id"), nullable=False),
    Column("source_format", String, nullable=False),
    Column("file_name", String, nullable=False),
    Column("file_sha256", String, nullable=False),
    Column("period_start", Date),
    Column("period_end", Date),
    Column("imported_at", DateTime, nullable=False),
    Column("rows_new", Integer, nullable=False, default=0),
    Column("rows_duplicate", Integer, nullable=False, default=0),
    Column("warnings", Text, nullable=False, default=""),
)


def _batch_fk() -> Column[int]:
    return Column("batch_id", ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False)


def _key() -> Column[str]:
    return Column("natural_key", String, nullable=False, unique=True)


instrument = Table(
    "instrument",
    metadata,
    Column("id", Integer, primary_key=True),
    _key(),  # conid when known, else asset_class:symbol
    Column("symbol", String, nullable=False),
    # ",EXSA,EXSAd," – all symbols incl. the primary one, comma-delimited for LIKE lookups
    Column("symbols", String, nullable=False),
    Column("asset_class", String, nullable=False),
    Column("description", String, nullable=False, default=""),
    Column("conid", String),
    Column("isin", String, index=True),
    Column("listing_exchange", String),
    Column("instrument_type", String),
    Column("issuer_country", String),
)

trade = Table(
    "trade",
    metadata,
    Column("id", Integer, primary_key=True),
    _key(),
    _batch_fk(),
    Column("account_id", String, nullable=False, index=True),
    Column("asset_class", String, nullable=False),
    Column("symbol", String, nullable=False, index=True),
    Column("currency", String, nullable=False),
    Column("trade_datetime", DateTime, nullable=False, index=True),
    Column("quantity", DecimalText, nullable=False),
    Column("price", DecimalText, nullable=False),
    Column("proceeds", DecimalText, nullable=False),
    Column("commission", DecimalText, nullable=False),
    Column("commission_currency", String, nullable=False),
    Column("basis", DecimalText),
    Column("realized_pnl", DecimalText),
    Column("codes", String, nullable=False, default=""),
    Column("conid", String),
    Column("isin", String),
    Column("trade_id", String),
    Column("transaction_id", String),
    Column("order_id", String, index=True),
    Column("order_type", String),
    Column("order_reference", String),
    Column("order_time", DateTime),
    Column("fx_rate_to_base", DecimalText),
)

closed_lot = Table(
    "closed_lot",
    metadata,
    Column("id", Integer, primary_key=True),
    _key(),
    _batch_fk(),
    Column("account_id", String, nullable=False),
    Column("asset_class", String, nullable=False),
    Column("symbol", String, nullable=False),
    Column("currency", String, nullable=False),
    Column("close_datetime", DateTime, nullable=False, index=True),
    Column("quantity", DecimalText, nullable=False),
    Column("open_datetime", DateTime, nullable=False),
    Column("cost", DecimalText, nullable=False),
    Column("realized_pnl", DecimalText, nullable=False),
    Column("conid", String, index=True),
    Column("isin", String),
    Column("open_transaction_id", String),
)

fx_rate = Table(
    "fx_rate",
    metadata,
    Column("id", Integer, primary_key=True),
    _key(),
    _batch_fk(),
    Column("date", Date, nullable=False, index=True),
    Column("from_currency", String, nullable=False),
    Column("to_currency", String, nullable=False),
    Column("rate", DecimalText, nullable=False),
    Column("source", String, nullable=False),
)

cash_transaction = Table(
    "cash_transaction",
    metadata,
    Column("id", Integer, primary_key=True),
    _key(),
    _batch_fk(),
    Column("account_id", String, nullable=False, index=True),
    Column("type", String, nullable=False, index=True),
    Column("currency", String, nullable=False),
    Column("date", Date, nullable=False, index=True),
    Column("amount", DecimalText, nullable=False),
    Column("description", String, nullable=False),
    Column("symbol", String),
    Column("isin", String),
    Column("code", String, nullable=False, default=""),
    Column("conid", String),
    Column("ex_date", Date),
    Column("action_id", String, index=True),
    Column("transaction_id", String),
    Column("fx_rate_to_base", DecimalText),
)

corporate_action = Table(
    "corporate_action",
    metadata,
    Column("id", Integer, primary_key=True),
    _key(),
    _batch_fk(),
    Column("account_id", String, nullable=False),
    Column("currency", String, nullable=False),
    Column("report_date", Date, nullable=False),
    Column("action_datetime", DateTime, nullable=False),
    Column("description", String, nullable=False),
    Column("quantity", DecimalText, nullable=False),
    Column("proceeds", DecimalText, nullable=False),
    Column("value", DecimalText, nullable=False),
    Column("symbol", String),
    Column("isin", String),
    Column("conid", String),
    Column("action_type", String),
    Column("action_id", String),
    Column("transaction_id", String),
)

open_position = Table(
    "open_position",
    metadata,
    Column("id", Integer, primary_key=True),
    _key(),
    _batch_fk(),
    Column("account_id", String, nullable=False),
    Column("as_of", Date, nullable=False),
    Column("asset_class", String, nullable=False),
    Column("symbol", String, nullable=False),
    Column("currency", String, nullable=False),
    Column("quantity", DecimalText, nullable=False),
    Column("cost_basis", DecimalText, nullable=False),
    Column("close_price", DecimalText, nullable=False),
    Column("value", DecimalText, nullable=False),
    Column("unrealized_pnl", DecimalText, nullable=False),
    Column("conid", String),
    Column("isin", String),
    Column("level", String, nullable=False, default="SUMMARY"),
    Column("open_datetime", DateTime),
)

dividend_detail = Table(
    "dividend_detail",
    metadata,
    Column("id", Integer, primary_key=True),
    _key(),
    _batch_fk(),
    Column("account_id", String, nullable=False),
    Column("currency", String, nullable=False),
    Column("symbol", String, nullable=False),
    Column("conid", String, nullable=False),
    Column("country", String, nullable=False),
    Column("report_date", Date, nullable=False),
    Column("ex_date", Date),
    Column("gross", DecimalText, nullable=False),
    Column("gross_in_base", DecimalText, nullable=False),
    Column("withhold", DecimalText, nullable=False),
    Column("withhold_in_base", DecimalText, nullable=False),
    Column("revenue_component", String, nullable=False, default=""),
)

fx_income = Table(
    "fx_income",
    metadata,
    Column("id", Integer, primary_key=True),
    _key(),
    _batch_fk(),
    Column("account_id", String, nullable=False),
    Column("year", Integer, nullable=False),
    Column("currency", String, nullable=False),
    Column("description", String, nullable=False),
    Column("date_acquired", Date, nullable=False),
    Column("source_of_acquisition", String, nullable=False),
    Column("date_disposed", Date, nullable=False),
    Column("source_of_disposition", String, nullable=False),
    Column("proceeds", DecimalText, nullable=False),
    Column("cost", DecimalText, nullable=False),
    Column("income", DecimalText, nullable=False),
    Column("code", String, nullable=False, default=""),
)

# Official rates downloaded from ČNB / ECB (not tied to an import batch).
reference_rate = Table(
    "reference_rate",
    metadata,
    Column("source", String, primary_key=True),  # CNB: CZK per unit, ECB: units per EUR
    Column("currency", String, primary_key=True),
    Column("date", Date, primary_key=True),
    Column("rate", DecimalText, nullable=False),
)

# Years for which a source has been downloaded completely (past years never change).
reference_rate_year = Table(
    "reference_rate_year",
    metadata,
    Column("source", String, primary_key=True),
    Column("year", Integer, primary_key=True),
    Column("fetched_at", DateTime, nullable=False),
)

# Application settings as JSON values (rate sources, default tax country, ...).
# A new table needs no schema bump: create_all adds it to existing databases.
app_setting = Table(
    "app_setting",
    metadata,
    Column("key", String, primary_key=True),
    Column("value", Text, nullable=False),
)

# User annotations are never touched by imports (ZADANI.md §3.2).
annotation = Table(
    "annotation",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("entity", String, nullable=False),
    Column("entity_key", String, nullable=False),
    Column("exit_reason", String),
    Column("tags", String, nullable=False, default=""),
    Column("note", Text, nullable=False, default=""),
    Column("sk_dividend_profit_year", Integer),
)

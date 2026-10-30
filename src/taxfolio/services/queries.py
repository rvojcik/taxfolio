"""Read-side queries shared by the CLI and the desktop UI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Engine, func, select

from taxfolio.engine.exit_classifier import TradeReason, classify
from taxfolio.storage import schema


@dataclass(frozen=True)
class BatchRow:
    id: int
    imported_at: datetime
    file_name: str
    source_format: str
    account_id: str
    period_start: date | None
    period_end: date | None
    rows_new: int
    rows_duplicate: int
    warnings: str


@dataclass(frozen=True)
class TradeRow:
    id: int
    account_id: str
    trade_datetime: datetime
    asset_class: str
    symbol: str
    description: str
    isin: str | None
    currency: str
    quantity: Decimal
    price: Decimal
    proceeds: Decimal
    commission: Decimal
    commission_currency: str
    realized_pnl: Decimal | None
    codes: str
    order_id: str | None = None
    trade_id: str | None = None
    order_type: str | None = None
    order_time: datetime | None = None
    order_reference: str | None = None

    @property
    def side(self) -> str:
        return "BUY" if self.quantity > 0 else "SELL"

    @property
    def reason(self) -> TradeReason:
        return classify(
            codes=self.codes,
            order_type=self.order_type,
            order_time=self.order_time,
            trade_datetime=self.trade_datetime,
            order_reference=self.order_reference,
            realized_pnl=self.realized_pnl,
        )


def list_batches(engine: Engine) -> list[BatchRow]:
    b = schema.import_batch
    with engine.connect() as conn:
        rows = conn.execute(select(b).order_by(b.c.id.desc())).mappings()
        return [
            BatchRow(
                id=r["id"],
                imported_at=r["imported_at"],
                file_name=r["file_name"],
                source_format=r["source_format"],
                account_id=r["account_id"],
                period_start=r["period_start"],
                period_end=r["period_end"],
                rows_new=r["rows_new"],
                rows_duplicate=r["rows_duplicate"],
                warnings=r["warnings"],
            )
            for r in rows
        ]


def list_accounts(engine: Engine) -> list[tuple[str, str, str]]:
    a = schema.account
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(select(a.c.account_id, a.c.name, a.c.base_currency))]


def list_trades(
    engine: Engine,
    *,
    account_id: str | None = None,
    year: int | None = None,
    asset_class: str | None = None,
) -> list[TradeRow]:
    t, i = schema.trade, schema.instrument
    # Activity Statements carry no conid on trades; match the trade symbol against all known aliases.
    same_instrument = (i.c.symbols.contains("," + t.c.symbol + ","), i.c.asset_class == t.c.asset_class)
    desc = select(i.c.description).where(*same_instrument).limit(1).scalar_subquery()
    isin = select(i.c.isin).where(*same_instrument).limit(1).scalar_subquery()
    columns = [c for c in t.c if c.name != "isin"]
    q = select(
        *columns, t.c.isin.label("trade_isin"), desc.label("description"), isin.label("isin")
    ).order_by(t.c.trade_datetime.desc())
    if account_id:
        q = q.where(t.c.account_id == account_id)
    if year:
        q = q.where(func.strftime("%Y", t.c.trade_datetime) == str(year))
    if asset_class:
        q = q.where(t.c.asset_class == asset_class)
    with engine.connect() as conn:
        return [
            TradeRow(
                id=r["id"],
                account_id=r["account_id"],
                trade_datetime=r["trade_datetime"],
                asset_class=r["asset_class"],
                symbol=r["symbol"],
                description=r["description"] or "",
                isin=r["trade_isin"] or r["isin"],
                currency=r["currency"],
                quantity=r["quantity"],
                price=r["price"],
                proceeds=r["proceeds"],
                commission=r["commission"],
                commission_currency=r["commission_currency"],
                realized_pnl=r["realized_pnl"],
                codes=r["codes"],
                order_id=r["order_id"],
                trade_id=r["trade_id"],
                order_type=r["order_type"],
                order_time=r["order_time"],
                order_reference=r["order_reference"],
            )
            for r in conn.execute(q).mappings()
        ]


def available_years(engine: Engine) -> list[int]:
    t = schema.trade
    with engine.connect() as conn:
        years = conn.execute(select(func.distinct(func.strftime("%Y", t.c.trade_datetime)))).scalars()
        return sorted((int(y) for y in years if y), reverse=True)


def table_counts(engine: Engine) -> dict[str, int]:
    tables = [
        schema.instrument,
        schema.trade,
        schema.closed_lot,
        schema.cash_transaction,
        schema.corporate_action,
        schema.open_position,
        schema.dividend_detail,
        schema.fx_income,
        schema.fx_rate,
    ]
    with engine.connect() as conn:
        return {tbl.name: conn.execute(select(func.count()).select_from(tbl)).scalar_one() for tbl in tables}

"""Import parsed files into the database with deduplication."""

from __future__ import annotations

import dataclasses
import hashlib
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Column, Connection, Engine, Table, delete, func, select, update
from sqlalchemy.dialects.sqlite import insert

from taxfolio.domain.models import ParsedFile
from taxfolio.i18n import _
from taxfolio.importers import flex_xml
from taxfolio.importers.detect import parse_file
from taxfolio.storage import schema

# Tables that both Activity Statements and Flex Queries fill. Flex data is richer (execution level,
# order types, IDs), so for a period covered by a Flex import the Activity Statement rows are dropped.
# table name: (table, date column, ParsedFile list attribute, record date attribute)
_SHARED_TABLES: list[tuple[Table, str, str, str]] = [
    (schema.trade, "trade_datetime", "trades", "trade_datetime"),
    (schema.cash_transaction, "date", "cash", "date"),
    (schema.corporate_action, "action_datetime", "corporate_actions", "action_datetime"),
    (schema.open_position, "as_of", "open_positions", "as_of"),
]


@dataclass(frozen=True)
class ImportResult:
    file_name: str
    source_format: str
    account_id: str
    batch_id: int
    new_rows: dict[str, int]
    duplicate_rows: dict[str, int]
    warnings: list[str]

    @property
    def total_new(self) -> int:
        return sum(self.new_rows.values())

    @property
    def total_duplicate(self) -> int:
        return sum(self.duplicate_rows.values())


def import_file(engine: Engine, path: Path) -> ImportResult:
    parsed = parse_file(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return store(engine, parsed, path.name, digest)


def store(engine: Engine, parsed: ParsedFile, file_name: str, file_sha256: str) -> ImportResult:
    new: dict[str, int] = {}
    dup: dict[str, int] = {}
    with engine.begin() as conn:
        _upsert_account(conn, parsed)
        batch_pk = conn.execute(
            schema.import_batch.insert().values(
                account_id=parsed.account.account_id,
                source_format=parsed.source_format,
                file_name=file_name,
                file_sha256=file_sha256,
                period_start=parsed.period_start,
                period_end=parsed.period_end,
                imported_at=datetime.now(),
                warnings="\n".join(parsed.warnings),
            )
        ).inserted_primary_key
        assert batch_pk is not None
        batch_id: int = batch_pk[0]

        _upsert_instruments(conn, parsed)
        warnings = list(parsed.warnings)
        if parsed.source_format == flex_xml.FORMAT:
            removed = _drop_superseded_activity_rows(conn, parsed)
            if removed:
                warnings.append(
                    _("Nahrazeno {count} záznamů z Activity Statementu daty z Flex Query").format(
                        count=removed
                    )
                )
        else:
            skipped = _skip_rows_covered_by_flex(conn, parsed)
            if skipped:
                warnings.append(
                    _("Přeskočeno {count} záznamů – období už pokrývá Flex Query").format(count=skipped)
                )
        for table, records in (
            (schema.trade, parsed.trades),
            (schema.closed_lot, parsed.closed_lots),
            (schema.cash_transaction, parsed.cash),
            (schema.corporate_action, parsed.corporate_actions),
            (schema.open_position, parsed.open_positions),
            (schema.dividend_detail, parsed.dividend_details),
            (schema.fx_income, parsed.fx_income),
            (schema.fx_rate, parsed.fx_rates),
        ):
            if not records:
                continue
            n_new = _insert_dedup(conn, table, batch_id, records)
            new[table.name] = n_new
            dup[table.name] = len(records) - n_new
        _apply_dividend_countries(conn)

        conn.execute(
            update(schema.import_batch)
            .where(schema.import_batch.c.id == batch_id)
            .values(
                rows_new=sum(new.values()), rows_duplicate=sum(dup.values()), warnings="\n".join(warnings)
            )
        )
    return ImportResult(
        file_name, parsed.source_format, parsed.account.account_id, batch_id, new, dup, warnings
    )


def undo_import(engine: Engine, batch_id: int) -> None:
    """Remove a batch and the rows it introduced (rows first seen in that batch)."""
    undo_imports(engine, [batch_id])


def undo_imports(engine: Engine, batch_ids: Sequence[int]) -> None:
    """Remove several batches at once (one transaction: all or nothing)."""
    with engine.begin() as conn:
        conn.execute(delete(schema.import_batch).where(schema.import_batch.c.id.in_(list(batch_ids))))


def _flex_periods(conn: Connection, account_id: str) -> list[tuple[Any, Any]]:
    b = schema.import_batch
    rows = conn.execute(
        select(b.c.period_start, b.c.period_end).where(
            b.c.account_id == account_id, b.c.source_format == flex_xml.FORMAT
        )
    )
    return [(r.period_start, r.period_end) for r in rows if r.period_start and r.period_end]


def _as_date(value: Any) -> Any:
    return value.date() if isinstance(value, datetime) else value


def _skip_rows_covered_by_flex(conn: Connection, parsed: ParsedFile) -> int:
    periods = _flex_periods(conn, parsed.account.account_id)
    if not periods:
        return 0
    skipped = 0
    for _table, _col, list_attr, date_attr in _SHARED_TABLES:
        records = getattr(parsed, list_attr)
        kept = [
            r
            for r in records
            if not any(start <= _as_date(getattr(r, date_attr)) <= end for start, end in periods)
        ]
        skipped += len(records) - len(kept)
        setattr(parsed, list_attr, kept)
    return skipped


def _drop_superseded_activity_rows(conn: Connection, parsed: ParsedFile) -> int:
    if not (parsed.period_start and parsed.period_end):
        return 0
    b = schema.import_batch
    activity_batches = select(b.c.id).where(
        b.c.account_id == parsed.account.account_id, b.c.source_format != flex_xml.FORMAT
    )
    removed = 0
    for table, date_col, _list_attr, _date_attr in _SHARED_TABLES:
        col: Column[Any] = table.c[date_col]
        result = conn.execute(
            delete(table).where(
                table.c.batch_id.in_(activity_batches),
                func.date(col) >= parsed.period_start.isoformat(),
                func.date(col) <= parsed.period_end.isoformat(),
            )
        )
        removed += max(result.rowcount, 0)
    return removed


def _record_values(record: Any) -> dict[str, Any]:
    values = dataclasses.asdict(record)
    if "codes" in values:
        values["codes"] = ";".join(values["codes"])
    return values


def natural_keys(table_name: str, rows: Sequence[dict[str, Any]]) -> list[str]:
    """Content hash + occurrence index, so identical rows within one file stay distinct."""
    seen: Counter[str] = Counter()
    keys = []
    for values in rows:
        base = "|".join(f"{k}={values[k]}" for k in sorted(values))
        seen[base] += 1
        digest = hashlib.sha1(f"{table_name}|{base}|{seen[base]}".encode()).hexdigest()
        keys.append(digest)
    return keys


def _insert_dedup(conn: Connection, table: Table, batch_id: int, records: Iterable[Any]) -> int:
    rows = [_record_values(r) for r in records]
    keys = natural_keys(table.name, rows)
    payload = [{**row, "natural_key": key, "batch_id": batch_id} for row, key in zip(rows, keys, strict=True)]
    result = conn.execute(insert(table).on_conflict_do_nothing(index_elements=["natural_key"]), payload)
    # executemany rowcount is the number of rows actually inserted in SQLite
    return max(result.rowcount, 0)


def _upsert_account(conn: Connection, parsed: ParsedFile) -> None:
    acc = parsed.account
    stmt = insert(schema.account).values(
        account_id=acc.account_id, name=acc.name, base_currency=acc.base_currency
    )
    conn.execute(
        stmt.on_conflict_do_update(
            index_elements=["account_id"],
            set_={"name": stmt.excluded.name, "base_currency": stmt.excluded.base_currency},
        )
    )


def _upsert_instruments(conn: Connection, parsed: ParsedFile) -> None:
    for inst in parsed.instruments:
        values = dataclasses.asdict(inst)
        del values["aliases"]
        values["symbols"] = "," + ",".join(inst.all_symbols) + ","
        key = inst.conid or f"{inst.asset_class}:{inst.symbol}"
        stmt = insert(schema.instrument).values(natural_key=key, **values)
        # Keep a country that came from the Dividend Report (more authoritative than ISIN prefix).
        update_values = {k: stmt.excluded[k] for k in values if k != "issuer_country"}
        conn.execute(stmt.on_conflict_do_update(index_elements=["natural_key"], set_=update_values))


def _apply_dividend_countries(conn: Connection) -> None:
    """Take the source country from Dividend Reports, whichever file was imported first."""
    inst, div = schema.instrument, schema.dividend_detail
    country = (
        select(div.c.country)
        .where(div.c.conid == inst.c.conid, div.c.country != "")
        .limit(1)
        .scalar_subquery()
    )
    conn.execute(update(inst).where(country.is_not(None)).values(issuer_country=country))

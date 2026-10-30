"""Format-independent report document: titled sections of tables, rendered to XLSX or PDF."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

Cell = str | int | Decimal | date | None


@dataclass
class Table:
    title: str
    headers: list[str]
    rows: list[list[Cell]] = field(default_factory=list)


@dataclass
class Document:
    title: str
    subtitle: str = ""
    summary: list[str] = field(default_factory=list)  # short paragraphs above the tables
    tables: list[Table] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # warnings and disclaimers at the end
    generated_at: datetime = field(default_factory=datetime.now)


def cents(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(Decimal("0.01"))


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return (
            f"{value:,.2f}".replace(",", " ") if value.as_tuple().exponent == -2 else f"{value.normalize():f}"
        )
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    return str(value)

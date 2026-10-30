"""Low-level reader for IBKR multi-section CSV files.

IBKR reports (Activity Statement, Dividend Report, FX Income Worksheet) share one layout:
column 0 is the section name, column 1 the row kind (Header/Data/SubTotal/Total/Notes) and the
remaining columns are values. A section can contain several Header rows (e.g. Trades has one for
stocks and another for forex); each Data row belongs to the most recent Header of its section.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


@dataclass(frozen=True)
class Row:
    section: str
    kind: str
    values: dict[str, str]
    line_no: int

    def get(self, key: str, default: str = "") -> str:
        return self.values.get(key, default).strip()


def read_sections(path: Path) -> dict[str, list[Row]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return group_rows(csv.reader(fh))


def group_rows(lines: Iterable[list[str]]) -> dict[str, list[Row]]:
    headers: dict[str, list[str]] = {}
    out: dict[str, list[Row]] = {}
    for line_no, raw in enumerate(lines, start=1):
        if len(raw) < 2:
            continue
        section, kind, cells = raw[0].strip(), raw[1].strip(), raw[2:]
        if kind == "Header":
            headers[section] = [c.strip() for c in cells]
            continue
        header = headers.get(section)
        if header is None:
            continue
        values = {name: cells[i] if i < len(cells) else "" for i, name in enumerate(header) if name}
        out.setdefault(section, []).append(Row(section, kind, values, line_no))
    return out


def iter_data(rows: Iterable[Row]) -> Iterator[Row]:
    return (r for r in rows if r.kind == "Data")


_PAREN_NEG = re.compile(r"^\((.*)\)$")


def parse_decimal(text: str) -> Decimal:
    """Parse IBKR numbers: '1,234.5', '(0.93)' (negative), '' or '--' (zero)."""
    s = text.strip().replace(",", "")
    if s in ("", "--", "-"):
        return Decimal(0)
    neg = False
    if m := _PAREN_NEG.match(s):
        s, neg = m.group(1), True
    try:
        value = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {text!r}") from exc
    return -value if neg else value


def parse_optional_decimal(text: str) -> Decimal | None:
    return None if text.strip() in ("", "--") else parse_decimal(text)


def parse_date(text: str) -> date:
    s = text.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unknown date format: {text!r}")


def parse_datetime(text: str) -> datetime:
    s = text.strip()
    for fmt in ("%Y-%m-%d, %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d;%H%M%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"unknown datetime format: {text!r}")


def read_head(path: Path, size: int = 1024) -> str:
    """First characters of a file (BOM and leading whitespace stripped) for format detection."""
    with path.open(encoding="utf-8-sig", errors="replace") as fh:
        return fh.read(size).lstrip()

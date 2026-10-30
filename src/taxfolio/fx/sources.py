"""Download and parse official exchange rates.

* ČNB yearly file: ``Datum|1 AUD|...|100 HUF|...`` with dd.mm.yyyy dates and decimal commas;
  the header repeats whenever the currency set changes. Rates are CZK per ``amount`` units.
* ECB history (zip with one CSV): ``Date,USD,JPY,...`` – units of currency per 1 EUR, ``N/A`` gaps.
"""

from __future__ import annotations

import csv
import io
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

CNB_YEAR_URL = (
    "https://www.cnb.cz/cs/financni-trhy/devizovy-trh/kurzy-devizoveho-trhu/"
    "kurzy-devizoveho-trhu/rok.txt?rok={year}"
)
ECB_HISTORY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"

CNB = "CNB"  # CZK per 1 unit of currency
ECB = "ECB"  # units of currency per 1 EUR


@dataclass(frozen=True)
class RateRow:
    source: str
    currency: str
    date: date
    rate: Decimal


def _download(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "taxfolio"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 – fixed https URLs
        data: bytes = resp.read()
        return data


def parse_cnb_year(text: str) -> list[RateRow]:
    rows: list[RateRow] = []
    header: list[tuple[str, Decimal]] = []
    for line in text.splitlines():
        parts = line.strip().split("|")
        if len(parts) < 2:
            continue
        if parts[0] == "Datum":
            header = []
            for col in parts[1:]:
                units, code = col.split()
                header.append((code, Decimal(units)))
            continue
        day = datetime.strptime(parts[0], "%d.%m.%Y").date()
        for (code, amount), value in zip(header, parts[1:], strict=False):
            if value:
                rows.append(RateRow(CNB, code, day, Decimal(value.replace(",", ".")) / amount))
    return rows


def parse_ecb_history(csv_text: str, years: set[int] | None = None) -> list[RateRow]:
    rows: list[RateRow] = []
    for rec in csv.DictReader(io.StringIO(csv_text)):
        day = date.fromisoformat(rec["Date"])
        if years and day.year not in years:
            continue
        for code, value in rec.items():
            if code in ("Date", "") or code is None or not value or value == "N/A":
                continue
            rows.append(RateRow(ECB, code, day, Decimal(value)))
    return rows


def fetch_cnb_year(year: int) -> list[RateRow]:
    return parse_cnb_year(_download(CNB_YEAR_URL.format(year=year)).decode("utf-8"))


def fetch_ecb(years: set[int]) -> list[RateRow]:
    with zipfile.ZipFile(io.BytesIO(_download(ECB_HISTORY_URL))) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".csv"))
        return parse_ecb_history(zf.read(name).decode("utf-8"), years)

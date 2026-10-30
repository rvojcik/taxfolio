"""Parser for the IBKR FX Income Worksheet CSV (Reports → Tax → FX Income)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from taxfolio.domain.models import AccountInfo, FxIncomeLine, ParsedFile
from taxfolio.importers.ib_csv import iter_data, parse_date, parse_decimal, read_sections

FORMAT = "ibkr_fx_income_worksheet_csv"


def is_fx_worksheet(head: str) -> bool:
    return head.startswith("ReportSummary,Header,Title,Year")


def parse(path: Path) -> ParsedFile:
    sections = read_sections(path)
    summary = next(iter_data(sections.get("ReportSummary", [])), None)
    if summary is None or summary.get("Title") != "FX Income Worksheet":
        raise ValueError(f"{path.name}: not an IBKR FX Income Worksheet")
    account_id = summary.get("AccountID")
    year = int(summary.get("Year"))
    result = ParsedFile(
        source_format=FORMAT,
        account=AccountInfo(account_id, summary.get("AccountName"), summary.get("FunctionalCurrency")),
        period_start=date(year, 1, 1),
        period_end=date(year, 12, 31),
    )
    for r in iter_data(sections.get("FXDetail", [])):
        result.fx_income.append(
            FxIncomeLine(
                account_id=account_id,
                year=year,
                currency=r.get("FxCurrency"),
                description=r.get("DescriptionOfCurrencyPosition"),
                date_acquired=parse_date(r.get("DateAcquired")),
                source_of_acquisition=r.get("SourceOfAcquisition"),
                date_disposed=parse_date(r.get("DateOfDisposition")),
                source_of_disposition=r.get("SourceOfDisposition"),
                proceeds=parse_decimal(r.get("Proceeds")),
                cost=parse_decimal(r.get("Cost")),
                income=parse_decimal(r.get("IncomeOrLoss")),
                code=r.get("Code"),
            )
        )
    return result

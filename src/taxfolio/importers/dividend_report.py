"""Parser for the IBKR Dividend Report CSV (Reports → Tax → Dividend Report)."""

from __future__ import annotations

from pathlib import Path

from taxfolio.domain.models import AccountInfo, DividendDetail, ParsedFile
from taxfolio.importers.ib_csv import iter_data, parse_date, parse_decimal, read_sections

FORMAT = "ibkr_dividend_report_csv"


def is_dividend_report(head: str) -> bool:
    return head.startswith("Account,Header,AccountNumber")


def parse(path: Path) -> ParsedFile:
    sections = read_sections(path)
    accounts = list(iter_data(sections.get("Account", [])))
    if not accounts or "DividendDetail" not in sections:
        raise ValueError(f"{path.name}: not an IBKR Dividend Report")
    acc = accounts[0]
    account_id = acc.get("AccountNumber")
    result = ParsedFile(
        source_format=FORMAT,
        account=AccountInfo(account_id, acc.get("Name"), acc.get("BaseCurrency")),
    )
    # "Summary" rows hold one line per payment; "RevenueComponent" rows split it by
    # income type. We keep the per-component split because it carries the revenue type.
    for r in iter_data(sections["DividendDetail"]):
        if r.get("DataDiscriminator") != "RevenueComponent":
            continue
        ex_date = r.get("ExDate")
        result.dividend_details.append(
            DividendDetail(
                account_id=account_id,
                currency=r.get("Currency"),
                symbol=r.get("Symbol"),
                conid=r.get("Conid"),
                country=r.get("Country"),
                report_date=parse_date(r.get("ReportDate")),
                ex_date=parse_date(ex_date) if ex_date else None,
                gross=parse_decimal(r.get("Gross")),
                gross_in_base=parse_decimal(r.get("GrossInBase")),
                withhold=parse_decimal(r.get("Withhold")),
                withhold_in_base=parse_decimal(r.get("WithholdInBase")),
                revenue_component=r.get("RevenueComponent"),
            )
        )
    if result.dividend_details:
        result.period_start = min(d.report_date for d in result.dividend_details)
        result.period_end = max(d.report_date for d in result.dividend_details)
    return result

"""Detect the format of an input file and dispatch to the matching parser."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from taxfolio.domain.models import ParsedFile
from taxfolio.i18n import _
from taxfolio.importers import activity_statement, dividend_report, flex_xml, fx_worksheet, xtb
from taxfolio.importers.ib_csv import read_head

_PARSERS: list[tuple[Callable[[str], bool], Callable[[Path], ParsedFile]]] = [
    (flex_xml.is_flex_xml, flex_xml.parse),
    (activity_statement.is_activity_statement, activity_statement.parse),
    (dividend_report.is_dividend_report, dividend_report.parse),
    (fx_worksheet.is_fx_worksheet, fx_worksheet.parse),
    (xtb.is_xtb_csv, xtb.parse),
]


class UnsupportedFormatError(ValueError):
    pass


def parse_file(path: Path) -> ParsedFile:
    if path.suffix.lower() == ".xlsx":
        if xtb.is_xtb_xlsx(path):
            return xtb.parse(path)
        raise UnsupportedFormatError(
            _("{file}: sešit neobsahuje list s peněžními operacemi XTB.").format(file=path.name)
        )
    head = read_head(path)
    for matches, parse in _PARSERS:
        if matches(head):
            return parse(path)
    raise UnsupportedFormatError(
        _(
            "{file}: neznámý formát. Podporováno: Flex Query XML, Activity Statement CSV, "
            "Dividend Report CSV, FX Income Worksheet CSV, XTB peněžní operace (CSV, XLSX)."
        ).format(file=path.name)
    )

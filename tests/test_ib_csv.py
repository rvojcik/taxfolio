from datetime import date, datetime
from decimal import Decimal

import pytest

from taxfolio.importers.ib_csv import group_rows, parse_date, parse_datetime, parse_decimal


@pytest.mark.parametrize(
    ("text", "expected"),
    [("1,234.5", "1234.5"), ("(0.93)", "-0.93"), ("-1.000092", "-1.000092"), ("", "0"), ("--", "0")],
)
def test_parse_decimal(text: str, expected: str) -> None:
    assert parse_decimal(text) == Decimal(expected)


def test_parse_decimal_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_decimal("abc")


def test_dates() -> None:
    assert parse_date("2025-08-01") == parse_date("20250801") == parse_date("08/01/2025") == date(2025, 8, 1)
    assert parse_datetime("2025-08-12, 04:39:35") == datetime(2025, 8, 12, 4, 39, 35)


def test_rows_follow_latest_header_of_their_section() -> None:
    sections = group_rows(
        [
            ["T", "Header", "A", "B"],
            ["T", "Data", "1", "2"],
            ["X", "Header", "Q"],
            ["X", "Data", "x"],
            ["T", "Header", "A", "C"],
            ["T", "Data", "3", "4"],
        ]
    )
    assert [r.values for r in sections["T"]] == [{"A": "1", "B": "2"}, {"A": "3", "C": "4"}]
    assert sections["X"][0].get("Q") == "x"

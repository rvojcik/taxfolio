"""Generic read-only Qt table model over a list of row objects."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Generic, TypeVar

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QColor

from taxfolio.ui import theme

T = TypeVar("T")

SORT_ROLE = Qt.ItemDataRole.UserRole + 1
_Index = QModelIndex | QPersistentModelIndex


@dataclass(frozen=True)
class Column(Generic[T]):
    title: str
    value: Callable[[T], Any]
    # Colour negative numbers red / positive green (for P/L columns)
    signed_color: bool = False


def _display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        # Drop IBKR's float noise like 1.000092 → keep up to 6 places, strip trailing zeros
        q = value.quantize(Decimal("0.000001")).normalize()
        return f"{q:,f}".replace(",", " ")
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M") if hasattr(value, "hour") else value.strftime("%Y-%m-%d")
    return str(value)


def _sort_key(value: Any) -> Any:
    """Qt can only compare plain types; Python dates would come back as opaque objects."""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


class RowTableModel(QAbstractTableModel, Generic[T]):
    def __init__(self, columns: Sequence[Column[T]], parent: Any = None) -> None:
        super().__init__(parent)
        self._columns = list(columns)
        self._rows: list[T] = []

    def set_rows(self, rows: Sequence[T]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def row_at(self, row: int) -> T:
        return self._rows[row]

    def rowCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._columns)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._columns[section].title
        return None

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        col = self._columns[index.column()]
        value = col.value(self._rows[index.row()])
        if role == Qt.ItemDataRole.DisplayRole:
            return _display(value)
        if role == SORT_ROLE:
            return _sort_key(value)
        if role == Qt.ItemDataRole.TextAlignmentRole and isinstance(value, (Decimal, int)):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole and col.signed_color and isinstance(value, Decimal):
            if value < 0:
                return QColor(theme.current().negative_text)
            if value > 0:
                return QColor(theme.current().positive_text)
        return None

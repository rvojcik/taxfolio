"""Taxes → 'Lze prodat bez daně': positions whose oldest lots already passed the time test."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from urllib.error import URLError

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from sqlalchemy import Engine

from taxfolio.fx.converter import MissingRateError
from taxfolio.i18n import _
from taxfolio.services.tax_free import TaxFreePosition
from taxfolio.tax.rules_loader import MissingRulesError
from taxfolio.ui.table_model import Column, RowTableModel
from taxfolio.ui.tax_cz_view import _c, _table

Loader = Callable[[Engine, str | None], list[TaxFreePosition]]
GAIN_COLUMN = 10  # "Zisk bez daně" in the table below


def _next(p: TaxFreePosition) -> str:
    if p.next_date is None:
        return "–"
    return _("{day}: {quantity} ks").format(
        day=f"{p.next_date:%d.%m.%Y}", quantity=f"{p.next_quantity.normalize():f}"
    )


class TaxFreeView(QWidget):
    """Independent of the selected tax year: what can be sold without tax today."""

    def __init__(self, engine: Engine, load: Loader, rule_note: str) -> None:
        super().__init__()
        self._engine, self._load = engine, load
        self._model: RowTableModel[TaxFreePosition] = RowTableModel(
            [
                Column(_("Symbol"), lambda p: p.symbol),
                Column(_("Název"), lambda p: p.description),
                Column(_("Bez daně (ks)"), lambda p: p.quantity),
                Column(_("Drženo (ks)"), lambda p: p.held),
                Column(_("Osvobozeno od"), lambda p: p.exempt_since),
                Column(_("Měna"), lambda p: p.currency),
                Column(_("Pořizovací cena"), lambda p: _c(p.cost)),
                Column(_("Poslední cena"), lambda p: _c(p.price) if p.price is not None else "–"),
                Column(_("Cena k"), lambda p: p.price_date or "–"),
                Column(_("Hodnota"), lambda p: _c(p.value) if p.value is not None else "–"),
                Column(
                    _("Zisk bez daně"), lambda p: p.gain if p.gain is not None else "–", signed_color=True
                ),
                Column(_("Další osvobození"), _next),
            ]
        )
        self._summary = QLabel()
        self._summary.setWordWrap(True)
        note = QLabel(
            rule_note
            + " "
            + _(
                "Prodej se páruje metodou FIFO (nejdřív nejstarší nákupy), takže uvedené množství lze prodat "
                "bez daně; prodej většího množství už zahrne i nákupy, které časový test nesplňují. "
                "Hodnota a zisk jsou podle ceny z posledního výpisu – skutečná cena se liší."
            )
        )
        note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self._summary)
        table = _table(self._model)
        # largest tax-free gain first (unknown price last)
        table.sortByColumn(GAIN_COLUMN, Qt.SortOrder.DescendingOrder)
        layout.addWidget(table, 1)
        layout.addWidget(note)

    def refresh(self, account: str | None) -> None:
        try:
            rows = self._load(self._engine, account)
        except (MissingRulesError, MissingRateError, URLError, OSError) as exc:
            self._model.set_rows([])
            self._summary.setText(f"⚠ {exc}")
            return
        self._model.set_rows(rows)
        if not rows:
            self._summary.setText(
                _("K {day} žádná pozice nesplňuje časový test.").format(day=f"{date.today():%d.%m.%Y}")
            )
            return
        self._summary.setText(
            _("K {day} lze bez daně prodat část nebo celou pozici u {count} titulů ({full} celé).").format(
                day=f"{date.today():%d.%m.%Y}", count=len(rows), full=sum(1 for p in rows if not p.partial)
            )
        )

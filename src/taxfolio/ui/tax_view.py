"""Taxes tab: one place for Czech and Slovak taxes, the country chosen at the top."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget
from sqlalchemy import Engine

from taxfolio.i18n import _
from taxfolio.services.settings import TAX_COUNTRIES, load_settings
from taxfolio.ui.tax_cz_view import TaxCzView
from taxfolio.ui.tax_sk_view import TaxSkView


class TaxView(QWidget):
    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self._engine = engine
        self._account: str | None = None
        self._year: int | None = None
        self.cz = TaxCzView(engine)
        self.sk = TaxSkView(engine)
        self._pages: dict[str, TaxCzView | TaxSkView] = {"CZ": self.cz, "SK": self.sk}

        self._stack = QStackedWidget()
        for page in self._pages.values():
            self._stack.addWidget(page)
        self._country = QComboBox()
        for code, name in TAX_COUNTRIES.items():
            self._country.addItem(_(name), code)
        self._country.currentIndexChanged.connect(self._show)

        top = QHBoxLayout()
        top.addWidget(QLabel(_("Země zdanění:")))
        top.addWidget(self._country)
        top.addStretch()
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._stack, 1)
        self.apply_settings()

    @property
    def country(self) -> str:
        return str(self._country.currentData())

    def set_country(self, code: str) -> None:
        self._country.setCurrentIndex(max(self._country.findData(code), 0))

    def apply_settings(self) -> None:
        """Switch to the default country from the settings."""
        self.set_country(load_settings(self._engine).tax_country)
        self._show()

    def set_scope(self, account: str | None, year: int | None) -> None:
        self._account, self._year = account, year
        self._show()

    def _show(self) -> None:
        # Only the visible country is computed; the other one refreshes when selected.
        page = self._pages[self.country]
        self._stack.setCurrentWidget(page)
        page.set_scope(self._account, self._year)

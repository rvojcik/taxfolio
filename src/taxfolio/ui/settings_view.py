"""Settings tab: default tax country and the exchange-rate source for every currency."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import Engine

from taxfolio import __version__
from taxfolio.fx.converter import (
    RATE_SOURCE_LABELS,
    TARGET_CURRENCIES,
    TAX_ACCEPTED_SOURCES,
    FxConverter,
    MissingRateError,
    RateRule,
    RateSource,
)
from taxfolio.i18n import LANGUAGES, N_, _, current_language
from taxfolio.services import rates_service
from taxfolio.services.settings import TAX_COUNTRIES, AppSettings, load_settings, save_settings
from taxfolio.ui.sources_view import SourcesBox
from taxfolio.ui.theme import APPEARANCES, primary

TARGET_TITLES = {
    "CZK": N_("Přepočet na CZK – české daně, přehledy v CZK"),
    "EUR": N_("Přepočet na EUR – slovenské daně, přehledy v EUR"),
}
# Currencies offered even when they do not appear in the data yet
COMMON_CURRENCIES = ("USD", "EUR", "CZK", "GBP", "PLN", "CHF")


def _num(value: Decimal, places: int = 4) -> str:
    return f"{value:.{places}f}".replace(".", ",")


# Rows visible in a rate table before it scrolls (about five currencies)
RATE_TABLE_MIN_HEIGHT = 200
# Space between the setting sections (cards with a title above)
SECTION_SPACING = 18


class RateTable(QTableWidget):
    """One row per currency: source combo, fixed-rate field, live preview of the value."""

    COLUMNS = (N_("Měna"), N_("Zdroj kurzu"), N_("Pevný kurz"), N_("Aktuální hodnota"), N_("Daňově"))

    def __init__(self, target: str) -> None:
        super().__init__(0, len(self.COLUMNS))
        self.target = target
        self.setHorizontalHeaderLabels([_(c) for c in self.COLUMNS])
        self.verticalHeader().hide()
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self._fx: FxConverter | None = None
        self._rows: list[tuple[str, QComboBox, QLineEdit]] = []

    def populate(self, currencies: list[str], settings: AppSettings, fx: FxConverter) -> None:
        self._fx = fx
        self._rows = []
        self.setRowCount(0)
        for ccy in currencies:
            if ccy == self.target:
                continue
            row = self.rowCount()
            self.insertRow(row)
            rule = settings.rule(self.target, ccy)
            label = QLabel(f"  1 {ccy}")
            source = QComboBox()
            for src, text in RATE_SOURCE_LABELS.items():
                source.addItem(_(text), src.value)
            source.setCurrentIndex(source.findData(rule.source.value))
            fixed = QLineEdit("" if rule.fixed is None else _num(rule.fixed, 6).rstrip("0").rstrip(","))
            fixed.setPlaceholderText(_("{target} za 1 {currency}").format(target=self.target, currency=ccy))
            self.setCellWidget(row, 0, label)
            self.setCellWidget(row, 1, source)
            self.setCellWidget(row, 2, fixed)
            self.setCellWidget(row, 3, QLabel())
            self.setCellWidget(row, 4, QLabel())
            self._rows.append((ccy, source, fixed))
            source.currentIndexChanged.connect(lambda _i, r=row: self._update_row(r))
            fixed.textChanged.connect(lambda _t, r=row: self._update_row(r))
            self._update_row(row)

    def _update_row(self, row: int) -> None:
        ccy, combo, fixed = self._rows[row]
        src = RateSource(combo.currentData())
        fixed.setEnabled(src is RateSource.FIXED)
        preview = self.cellWidget(row, 3)
        legal = self.cellWidget(row, 4)
        assert isinstance(preview, QLabel) and isinstance(legal, QLabel)
        preview.setText(self._preview(ccy, src, fixed.text()))
        self.resizeColumnToContents(3)
        ok = src in TAX_ACCEPTED_SOURCES[self.target]
        legal.setText("✔ " + _("přípustný") if ok else "⚠ " + _("zákon nepřipouští"))
        legal.setToolTip(
            "" if ok else _("Pro daňové přiznání tento zdroj kurzu nelze použít; výpočet upozorní.")
        )

    def _preview(self, ccy: str, src: RateSource, fixed_text: str) -> str:
        if src is RateSource.FIXED:
            try:
                value = _parse_rate(fixed_text)
            except ValueError as exc:
                return f"⚠ {exc}"
            return _("1 {currency} = {value} {target} (pevně)").format(
                currency=ccy, value=_num(value), target=self.target
            )
        fx = self._fx
        if fx is None:
            return ""
        try:
            if src is RateSource.GFR_ANNUAL:
                # The current year's unified rate exists only after 31 Dec; show the last full years.
                parts = []
                for year in (date.today().year - 1, date.today().year - 2):
                    try:
                        parts.append(f"{year}: {_num(fx.rate(ccy, date(year, 6, 30), self.target, src), 4)}")
                    except MissingRateError:
                        continue
                if not parts:
                    raise MissingRateError(_("kurzy ČNB za minulé roky nejsou stažené"))
                return f"1 {ccy} = " + " · ".join(parts) + f" {self.target}"
            day = fx.latest_date(src, ccy) or date.today()
            value = fx.rate(ccy, day, self.target, src)
            return f"1 {ccy} = {_num(value)} {self.target} ({day:%d.%m.%Y})"
        except MissingRateError as exc:
            return f"⚠ {exc}"

    def rules(self) -> dict[tuple[str, str], RateRule]:
        out = {}
        for ccy, combo, fixed in self._rows:
            src = RateSource(combo.currentData())
            value = _parse_rate(fixed.text()) if src is RateSource.FIXED else None
            out[(self.target, ccy)] = RateRule(src, value)
        return out


def _wrapped(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    return label


def _parse_rate(text: str) -> Decimal:
    try:
        value = Decimal(text.strip().replace(" ", "").replace(",", "."))
    except InvalidOperation:
        raise ValueError(_("zadejte pevný kurz (číslo)")) from None
    if value <= 0:
        raise ValueError(_("kurz musí být kladný"))
    return value


class SettingsView(QWidget):
    settings_changed = Signal()
    # language or appearance changed: the window is rebuilt with the new texts / colours
    rebuild_requested = Signal()
    # "download the current rates" – the main window does it off the UI thread
    rates_requested = Signal()
    update_check_requested = Signal()

    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self._engine = engine

        self._language = QComboBox()
        for code, name in LANGUAGES.items():
            self._language.addItem(name, code)  # language names stay in their own language
        general_box = QGroupBox(_("Obecné"))
        general_form = QFormLayout(general_box)
        general_form.addRow(_("Jazyk / Language:"), self._language)
        self._appearance = QComboBox()
        for value, name in APPEARANCES.items():
            self._appearance.addItem(_(name), value.value)
        general_form.addRow(_("Vzhled:"), self._appearance)
        self._check_updates = QCheckBox(_("Automaticky kontrolovat nové verze (jednou denně)"))
        check_now = QPushButton(_("Zkontrolovat teď"))
        check_now.clicked.connect(self.update_check_requested.emit)
        version_row = QHBoxLayout()
        version_row.addWidget(QLabel(__version__))
        version_row.addSpacing(16)
        version_row.addWidget(self._check_updates)
        version_row.addWidget(check_now)
        version_row.addStretch()
        general_form.addRow(_("Verze aplikace:"), version_row)

        self._country = QComboBox()
        for code, name in TAX_COUNTRIES.items():
            self._country.addItem(_(name), code)
        tax_box = QGroupBox(_("Daně"))
        tax_form = QFormLayout(tax_box)
        tax_form.addRow(_("Výchozí země zdanění:"), self._country)

        self.sources = SourcesBox(engine)

        self._tables = {target: RateTable(target) for target in TARGET_CURRENCIES}
        rate_box = QGroupBox(_("Kurzy měn"))
        rate_layout = QVBoxLayout(rate_box)
        rate_layout.addWidget(
            _wrapped(
                _(
                    "Pro každou měnu zvolte, odkud se kurz načítá. Pevný kurz se použije pro všechny dny. "
                    "Pro daňové přiznání zákon připouští v ČR kurz ČNB nebo jednotný kurz, v SR kurz ECB."
                )
            )
        )
        for target, table in self._tables.items():
            rate_layout.addWidget(QLabel(f"<b>{_(TARGET_TITLES[target])}</b>"))
            rate_layout.addWidget(table)

        save = primary(QPushButton(_("Uložit nastavení")))
        save.clicked.connect(self._save)
        reload_rates = QPushButton(_("Stáhnout aktuální kurzy ČNB a ECB"))
        reload_rates.clicked.connect(self._download)
        revert = QPushButton(_("Zahodit změny"))
        revert.clicked.connect(self.refresh)
        self._status = QLabel()
        self._status.setWordWrap(True)
        buttons = QHBoxLayout()
        buttons.addWidget(save)
        buttons.addWidget(revert)
        buttons.addWidget(reload_rates)
        buttons.addStretch()

        for table in self._tables.values():
            table.setMinimumHeight(RATE_TABLE_MIN_HEIGHT)
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setSpacing(SECTION_SPACING)  # more than the title–card gap, so a title belongs to its card
        cl.addWidget(general_box)
        cl.addWidget(tax_box)
        cl.addWidget(self.sources)
        cl.addWidget(rate_box, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll, 1)
        layout.addLayout(buttons)  # always visible below the scrolling content
        layout.addWidget(self._status)
        self.refresh()

    def refresh(self) -> None:
        settings = load_settings(self._engine)
        self._language.setCurrentIndex(
            max(self._language.findData(settings.language or current_language()), 0)
        )
        self._country.setCurrentIndex(max(self._country.findData(settings.tax_country), 0))
        self._loaded_appearance = settings.appearance
        self._appearance.setCurrentIndex(max(self._appearance.findData(settings.appearance), 0))
        self._check_updates.setChecked(settings.check_updates)
        self.sources.refresh()
        fx = rates_service.load_converter(self._engine)
        currencies = sorted(set(rates_service.used_currencies(self._engine)) | set(COMMON_CURRENCIES))
        for table in self._tables.values():
            table.populate(currencies, settings, fx)
        self._status.setText("")

    def _download(self) -> None:
        self._status.setText(_("Kurzy se stahují na pozadí – stav je v dolní liště okna."))
        self.rates_requested.emit()

    def _save(self) -> None:
        settings = AppSettings(
            tax_country=self._country.currentData(),
            language=self._language.currentData(),
            appearance=self._appearance.currentData(),
            check_updates=self._check_updates.isChecked(),
        )
        try:
            for table in self._tables.values():
                settings.rate_rules.update(table.rules())
        except ValueError as exc:
            QMessageBox.warning(self, _("Nastavení"), _("Nelze uložit: {error}").format(error=exc))
            return
        save_settings(self._engine, settings)
        self._status.setText(_("Nastavení uloženo; přehledy a daně se přepočítaly."))
        if settings.language != current_language() or settings.appearance != self._loaded_appearance:
            self.rebuild_requested.emit()
            return
        self.settings_changed.emit()

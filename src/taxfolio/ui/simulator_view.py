"""Sale simulator tab: tax impact of selling (part of) a position on a given day."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.error import URLError

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import Engine

from taxfolio.fx.converter import MissingRateError
from taxfolio.i18n import _
from taxfolio.services.simulator import (
    Holding,
    ImpactPoint,
    SimulatedLot,
    Simulation,
    holdings,
    impact_timeline,
    simulate_sale,
)
from taxfolio.tax.rules_loader import MissingRulesError
from taxfolio.ui.charts import tax_delta_chart, tax_impact_chart
from taxfolio.ui.table_model import Column, RowTableModel
from taxfolio.ui.tax_cz_view import _c, _table
from taxfolio.ui.theme import primary


def _qdate(value: QDate) -> date:
    return date(value.year(), value.month(), value.day())


def _parse(text: str) -> Decimal:
    return Decimal(text.strip().replace(" ", "").replace(",", "."))


def _signed(value: Decimal, unit: str) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value.quantize(Decimal('1')):,}".replace(",", " ") + f" {unit}"


class SimulatorView(QWidget):
    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self._engine = engine
        self._account: str | None = None
        self._holdings: list[Holding] = []

        self._position = QComboBox()
        self._position.currentIndexChanged.connect(self._position_changed)
        self._quantity = QLineEdit()
        self._price = QLineEdit()
        self._price_hint = QLabel()
        self._commission = QLineEdit("1")
        self._date = QDateEdit(QDate.currentDate())
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat("dd.MM.yyyy")
        run = primary(QPushButton(_("Spočítat dopad")))
        run.clicked.connect(self._run)

        form = QFormLayout()
        form.addRow(_("Pozice:"), self._position)
        form.addRow(_("Množství:"), self._quantity)
        price_row = QHBoxLayout()
        price_row.addWidget(self._price)
        price_row.addWidget(self._price_hint)
        form.addRow(_("Cena za kus:"), price_row)
        form.addRow(_("Poplatek:"), self._commission)
        form.addRow(_("Datum prodeje:"), self._date)
        form.addRow("", run)

        self._result = QLabel(_("Vyberte pozici, množství a cenu."))
        self._result.setTextFormat(Qt.TextFormat.RichText)
        self._result.setWordWrap(True)
        self._lots: RowTableModel[SimulatedLot] = RowTableModel(
            [
                Column(_("Nákup"), lambda s: s.match.open_datetime.date()),
                Column(_("Množství"), lambda s: s.match.quantity),
                Column(_("Držení (dny)"), lambda s: s.match.holding_days),
                Column(_("P/L"), lambda s: _c(s.match.pnl), signed_color=True),
                Column(_("P/L Kč"), lambda s: _c(s.pnl_czk), signed_color=True),
                Column(_("P/L €"), lambda s: _c(s.pnl_eur), signed_color=True),
                Column(_("ČR osvobozeno od"), lambda s: s.cz_exempt_from),
                Column(_("ČR"), lambda s: _("osvobozeno") if s.cz_exempt else _("zdanitelné")),
                Column(
                    _("SR osvobozeno od"),
                    lambda s: s.sk_exempt_from if s.sk_regulated else _("ne (není regulovaný trh)"),
                ),
                Column(_("SR"), lambda s: _("osvobozeno") if s.sk_exempt else _("zdanitelné")),
            ]
        )

        # Before/after per country (one chart each: CZK and EUR never share an axis) and the
        # impact of the same sale on later days
        self._charts = QGridLayout()
        self._charts.setColumnStretch(0, 1)
        self._charts.setColumnStretch(1, 1)
        lots_table = _table(self._lots, sortable=False)
        lots_table.setMinimumHeight(220)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.addLayout(form)
        cl.addWidget(self._result)
        cl.addLayout(self._charts)
        self._charts_note = QLabel()
        self._charts_note.setWordWrap(True)
        cl.addWidget(self._charts_note)
        cl.addWidget(lots_table, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    def _clear_charts(self) -> None:
        while (item := self._charts.takeAt(0)) is not None:
            if (w := item.widget()) is not None:
                w.setParent(None)
                w.deleteLater()

    def _fill_charts(self, sim: Simulation, timeline: list[ImpactPoint]) -> None:
        self._clear_charts()
        self._charts_note.setText(
            _(
                "Žlutá = prodej daň zvýší, zelená = sníží (ztráta započtená proti ziskům téhož roku). "
                "Graf podle data ukazuje stejný prodej ve dnech, kdy se daň mění: nákup splní časový test "
                "nebo začne nový rok. Budoucí roky počítají jen s tímto prodejem, s posledními známými "
                "pravidly a kurzy."
            )
        )
        year = sim.sale_date.year
        self._charts.addWidget(
            tax_impact_chart(
                _("ČR – daň z prodejů {year} (Kč)").format(year=year),
                sim.cz_tax_before,
                sim.cz_tax_after,
                "Kč",
            ),
            0,
            0,
        )
        self._charts.addWidget(
            tax_impact_chart(
                _("SR – daň a zdravotní pojištění {year} (€)").format(year=year),
                sim.sk_tax_before + sim.sk_health_before,
                sim.sk_tax_after + sim.sk_health_after,
                "€",
            ),
            0,
            1,
        )
        days = [(f"{p.sale_date:%d.%m.%y}", p) for p in timeline]
        self._charts.addWidget(
            tax_delta_chart(
                _("ČR – dopad prodeje podle data prodeje (Kč)"),
                [(day, p.cz_delta, p.reason) for day, p in days],
                "Kč",
            ),
            1,
            0,
        )
        self._charts.addWidget(
            tax_delta_chart(
                _("SR – dopad prodeje podle data prodeje (€)"),
                [(day, p.sk_delta, p.reason) for day, p in days],
                "€",
            ),
            1,
            1,
        )

    def set_scope(self, account: str | None, _year: int | None) -> None:
        self._account = account
        self.refresh()

    def refresh(self) -> None:
        self._holdings = holdings(self._engine, self._account)
        self._position.blockSignals(True)
        self._position.clear()
        for h in self._holdings:
            self._position.addItem(h.label)
        self._position.blockSignals(False)
        self._position_changed()

    def _current(self) -> Holding | None:
        idx = self._position.currentIndex()
        return self._holdings[idx] if 0 <= idx < len(self._holdings) else None

    def _position_changed(self) -> None:
        h = self._current()
        if h is None:
            return
        self._quantity.setText(f"{h.quantity.normalize():f}")
        self._price.setText(f"{h.last_price.normalize():f}" if h.last_price else "")
        self._price_hint.setText(
            _("{currency}, poslední známá cena k {day}").format(
                currency=h.currency, day=f"{h.last_price_date:%d.%m.%Y}"
            )
            if h.last_price_date
            else h.currency
        )

    def _run(self) -> None:
        h = self._current()
        if h is None:
            return
        try:
            qty, price, commission = (
                _parse(self._quantity.text()),
                _parse(self._price.text()),
                _parse(self._commission.text() or "0"),
            )
        except InvalidOperation:
            self._result.setText(_("⚠ Zadejte číselné hodnoty."))
            return
        try:
            sim = simulate_sale(
                self._engine,
                h,
                qty,
                price,
                _qdate(self._date.date()),
                None,  # exchange rates per the settings
                commission,
                self._account,
            )
        except (ValueError, MissingRulesError, MissingRateError, URLError, OSError) as exc:
            self._result.setText(f"⚠ {exc}")
            self._lots.set_rows([])
            self._clear_charts()
            self._charts_note.setText("")
            return
        self._lots.set_rows(sim.lots)
        try:
            timeline = impact_timeline(self._engine, sim, commission, None, self._account)
        except (ValueError, MissingRulesError, MissingRateError, URLError, OSError):
            timeline = [ImpactPoint(sim.sale_date, sim.cz_delta, sim.sk_delta, _("zvolené datum"))]
        self._fill_charts(sim, timeline)
        pnl = sum((lot.match.pnl for lot in sim.lots), Decimal(0))
        notes = "".join(f"<br>• {n}" for n in sim.notes)
        self._result.setText(
            _(
                "<p>Prodej {quantity} ks {symbol} za {price} {currency} dne {day}: zisk/ztráta {pnl} {currency}.</p>"
                "<p><b>ČR:</b> daň z prodejů v roce {year} {cz_before} → {cz_after} Kč (<b>{cz_delta}</b>)<br>"
                "<b>SR:</b> daň + zdravotní pojištění {sk_before} → {sk_after} € (<b>{sk_delta}</b>)"
            ).format(
                quantity=f"{qty.normalize():f}",
                symbol=h.symbol,
                price=price,
                currency=h.currency,
                day=f"{sim.sale_date:%d.%m.%Y}",
                pnl=f"{pnl:,.2f}",
                year=sim.sale_date.year,
                cz_before=f"{sim.cz_tax_before:,.0f}",
                cz_after=f"{sim.cz_tax_after:,.0f}",
                cz_delta=_signed(sim.cz_delta, "Kč"),
                sk_before=f"{sim.sk_tax_before + sim.sk_health_before:,.2f}",
                sk_after=f"{sim.sk_tax_after + sim.sk_health_after:,.2f}",
                sk_delta=_signed(sim.sk_delta, "€"),
            )
            + f"{notes}</p><p><i>"
            + _(
                "Počítá se jen s obchody z importovaných výpisů; prodeje v roce, které ještě nejsou "
                "importované, výsledek ovlivní."
            )
            + "</i></p>"
        )

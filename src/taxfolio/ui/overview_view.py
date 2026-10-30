"""Summary tab: key figures, basic charts and results by exit reason."""

from __future__ import annotations

from decimal import Decimal
from urllib.error import URLError

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import Engine

from taxfolio.fx.converter import MissingRateError
from taxfolio.i18n import _
from taxfolio.services.overview import (
    DISPLAY_CURRENCIES,
    CompanyDividends,
    Overview,
    ReasonStats,
    build_overview,
)
from taxfolio.ui.charts import bar_chart, cash_flow_chart, fmt
from taxfolio.ui.table_model import Column, RowTableModel
from taxfolio.ui.tax_cz_view import _c, _table


class StatTile(QFrame):
    """Headline number with a caption and a secondary line; text stays in ink colours."""

    def __init__(self, caption: str) -> None:
        super().__init__()
        self.setObjectName("tile")  # styled by ui/theme.py
        self._caption = QLabel(caption)
        self._caption.setObjectName("tileCaption")
        self._value = QLabel("–")
        font = self._value.font()
        font.setPointSizeF(font.pointSizeF() * 1.7)
        font.setBold(True)
        self._value.setFont(font)
        self._detail = QLabel("")
        self._detail.setObjectName("tileDetail")
        self._detail.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.addWidget(self._caption)
        layout.addWidget(self._value)
        layout.addWidget(self._detail)

    def set(self, value: str, detail: str = "") -> None:
        self._value.setText(value)
        self._detail.setText(detail)


class OverviewView(QWidget):
    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self._engine = engine
        self._account: str | None = None
        self._year: int | None = None

        self._currency = QComboBox()
        self._currency.addItems(list(DISPLAY_CURRENCIES))
        self._currency.currentIndexChanged.connect(self.refresh)
        self._scope = QLabel()
        self._status = QLabel()
        self._status.setWordWrap(True)

        self._tiles = {
            key: StatTile(caption)
            for key, caption in (
                ("portfolio", _("Hodnota portfolia")),
                ("unrealized", _("Nerealizovaný zisk/ztráta")),
                ("realized", _("Realizovaný zisk/ztráta")),
                ("winrate", _("Úspěšnost obchodů")),
                ("dividends", _("Dividendy (hrubě)")),
                ("fees", _("Poplatky")),
                ("deposits", _("Čisté vklady")),
            )
        }
        tiles = QGridLayout()
        for i, tile in enumerate(self._tiles.values()):
            tiles.addWidget(tile, i // 4, i % 4)

        self._reasons: RowTableModel[ReasonStats] = RowTableModel(
            [
                Column(_("Důvod výstupu"), lambda r: r.label),
                Column(_("Počet prodejů"), lambda r: r.count),
                Column(_("Realizovaný P/L"), lambda r: _c(r.pnl), signed_color=True),
                Column(
                    _("Průměr na prodej"),
                    lambda r: _c(r.pnl / r.count) if r.count else None,
                    signed_color=True,
                ),
            ]
        )
        self._companies: RowTableModel[CompanyDividends] = RowTableModel(
            [
                Column(_("Společnost"), lambda c: c.name),
                Column(_("Symbol"), lambda c: c.symbol),
                Column(_("Stát"), lambda c: c.country),
                Column(_("Výplat"), lambda c: c.payments),
                Column(_("Hrubě"), lambda c: _c(c.gross)),
                Column(_("Sraženo"), lambda c: _c(c.withheld)),
                Column(_("Čistě"), lambda c: _c(c.net)),
                Column(_("Podíl"), lambda c: self._share(c)),
            ]
        )
        self._companies_title = QLabel()
        self._companies_table = _table(self._companies)
        self._companies_table.sortByColumn(4, Qt.SortOrder.DescendingOrder)
        self._companies_table.setMinimumHeight(300)
        # Created once and re-added on every refresh (the charts around it are rebuilt)
        self._companies_box = QWidget()
        cb = QVBoxLayout(self._companies_box)
        cb.setContentsMargins(0, 0, 0, 0)
        cb.addWidget(self._companies_title)
        cb.addWidget(self._companies_table)
        self._dividends_total = Decimal(0)

        reasons_box = QWidget()
        rl = QVBoxLayout(reasons_box)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel(_("<b>Výsledky podle důvodu výstupu</b>")))
        reasons_table = _table(self._reasons)
        reasons_table.setMaximumHeight(150)
        rl.addWidget(reasons_table)

        self._charts = QGridLayout()
        self._charts.setColumnStretch(0, 1)
        self._charts.setColumnStretch(1, 1)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.addLayout(tiles)
        cl.addLayout(self._charts)
        cl.addWidget(reasons_box)
        cl.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)

        top = QHBoxLayout()
        top.addWidget(QLabel(_("Měna zobrazení:")))
        top.addWidget(self._currency)
        top.addSpacing(16)
        top.addWidget(self._scope)
        top.addStretch()
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(scroll, 1)
        layout.addWidget(self._status)

    def set_scope(self, account: str | None, year: int | None) -> None:
        self._account, self._year = account, year
        self.refresh()

    def refresh(self) -> None:
        currency = self._currency.currentText()
        try:
            ov = build_overview(self._engine, self._year, currency, self._account)
        except (MissingRateError, URLError, OSError) as exc:
            self._status.setText(f"⚠ {exc}")
            return
        period = _("rok {year}").format(year=self._year) if self._year else _("celé období")
        self._scope.setText(
            _("{period} · účet {account} · kurzy podle Nastavení ke dni pohybu").format(
                period=period, account=self._account or _("všechny")
            )
        )
        self._fill_tiles(ov)
        self._fill_charts(ov)
        self._reasons.set_rows(ov.reasons)
        self._dividends_total = ov.dividends_gross
        self._companies.set_rows(ov.dividends_by_company)
        self._companies_title.setText(
            "<b>" + _("Dividendy podle společnosti ({currency})").format(currency=currency) + "</b>"
        )
        self._status.setText("\n".join(f"⚠ {w}" for w in ov.warnings))

    def _share(self, company: CompanyDividends) -> str:
        if not self._dividends_total:
            return ""
        return f"{company.gross / self._dividends_total:.1%}"

    def _fill_tiles(self, ov: Overview) -> None:
        u = ov.currency
        t = self._tiles
        if ov.portfolio_value is not None and ov.portfolio_as_of is not None:
            t["portfolio"].set(
                fmt(ov.portfolio_value, u),
                _("k {day} (poslední výpis)").format(day=f"{ov.portfolio_as_of:%d.%m.%Y}"),
            )
            unrealized = ov.unrealized_pnl or Decimal(0)
            cost = ov.portfolio_value - unrealized
            pct = f" ({unrealized / cost:+.1%})" if cost else ""
            t["unrealized"].set(fmt(unrealized, u), _("oproti pořizovací ceně") + pct)
        else:
            t["portfolio"].set("–", _("žádný výpis s pozicemi"))
            t["unrealized"].set("–")
        t["realized"].set(
            fmt(ov.realized_pnl, u),
            _("zisky {gains} · ztráty {losses}").format(
                gains=fmt(ov.realized_gains, u), losses=fmt(ov.realized_losses, u)
            ),
        )
        if ov.win_rate is not None:
            t["winrate"].set(
                f"{ov.win_rate:.0%}",
                _("{wins} ziskových z {total} prodejů").format(
                    wins=ov.winning_trades, total=ov.closed_trades
                ),
            )
        else:
            t["winrate"].set("–", _("žádné prodeje"))
        t["dividends"].set(
            fmt(ov.dividends_gross, u),
            _("čistě {net} · sraženo {withheld}").format(
                net=fmt(ov.dividends_net, u), withheld=fmt(ov.withholding, u)
            ),
        )
        t["fees"].set(fmt(ov.fees, u), _("poplatky za obchody a vedení účtu"))
        t["deposits"].set(
            fmt(ov.net_deposits, u),
            _("vklady {deposits} · výběry {withdrawals}").format(
                deposits=fmt(ov.deposits, u), withdrawals=fmt(ov.withdrawals, u)
            ),
        )

    def _fill_charts(self, ov: Overview) -> None:
        while (item := self._charts.takeAt(0)) is not None:
            if (w := item.widget()) is not None and w is not self._companies_box:
                # Detach now – deleteLater alone leaves the old chart painted until the event loop runs
                w.setParent(None)
                w.deleteLater()
        u = ov.currency
        first = ov.monthly_pnl[0][0] if ov.monthly_pnl else ""
        period = "Q" if first.startswith("Q") else "Y" if len(first) == 4 else "M"
        pnl_title = {
            "M": _("Realizovaný zisk/ztráta po měsících ({currency})"),
            "Q": _("Realizovaný zisk/ztráta po čtvrtletích ({currency})"),
            "Y": _("Realizovaný zisk/ztráta po letech ({currency})"),
        }[period]
        div_title = {
            "M": _("Dividendy po měsících – hrubě ({currency})"),
            "Q": _("Dividendy po čtvrtletích – hrubě ({currency})"),
            "Y": _("Dividendy po letech – hrubě ({currency})"),
        }[period]
        cash_title = {
            "M": _("Vklady a výběry po měsících ({currency})"),
            "Q": _("Vklady a výběry po čtvrtletích ({currency})"),
            "Y": _("Vklady a výběry po letech ({currency})"),
        }[period]
        # Row 0: time series side by side; row 1: money in and out over the same periods (full width)
        self._charts.addWidget(
            bar_chart(pnl_title.format(currency=u), ov.monthly_pnl, u, diverging=True), 0, 0
        )
        self._charts.addWidget(bar_chart(div_title.format(currency=u), ov.monthly_dividends, u), 0, 1)
        self._charts.addWidget(
            cash_flow_chart(cash_title.format(currency=u), ov.monthly_deposits, ov.monthly_withdrawals, u),
            1,
            0,
            1,
            2,
        )
        # Row 2: by instrument
        self._charts.addWidget(
            bar_chart(
                _("Realizovaný zisk/ztráta podle titulu ({currency})").format(currency=u),
                ov.pnl_by_symbol,
                u,
                horizontal=True,
                diverging=True,
            ),
            2,
            0,
        )
        self._charts.addWidget(
            bar_chart(
                _("Složení portfolia ({currency})").format(currency=u), ov.holdings, u, horizontal=True
            ),
            2,
            1,
        )
        # Row 3: dividends per company – top 10 as a chart, every company in the table
        by_company = [(c.symbol, c.gross) for c in ov.dividends_by_company[:10]]
        rest = sum((c.gross for c in ov.dividends_by_company[10:]), Decimal(0))
        if rest:
            by_company.append((_("Ostatní"), rest))
        self._charts.addWidget(
            bar_chart(
                _("Dividendy podle společnosti – hrubě ({currency})").format(currency=u),
                by_company,
                u,
                horizontal=True,
            ),
            3,
            0,
        )
        self._charts.addWidget(self._companies_box, 3, 1)

"""Small QtCharts helpers following the project's chart rules.

Colours come from the reference data-viz palette (validated light and dark): gain/loss uses the
diverging pair blue ↔ red, a single magnitude uses blue only. Text stays in ink colours, bars carry
the identity; gridlines are hairlines; every bar has a hover tooltip.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSet,
    QChart,
    QChartView,
    QHorizontalStackedBarSeries,
    QStackedBarSeries,
    QValueAxis,
)
from PySide6.QtCore import QLocale, QMargins, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QApplication, QFrame, QToolTip

from taxfolio.i18n import _
from taxfolio.ui import theme as ui_theme


@dataclass(frozen=True)
class Theme:
    surface: str
    ink: str
    secondary: str
    muted: str
    grid: str
    baseline: str
    positive: str  # diverging pole + single-series colour
    negative: str


# Status colours of the reference palette: fixed in both themes, always paired with a text label
STATUS_GOOD = "#0ca30c"
STATUS_WARNING = "#fab219"

LIGHT = Theme("#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#2a78d6", "#e34948")
DARK = Theme("#1a1a19", "#f0efec", "#c3c2b7", "#898781", "#2c2c2a", "#383835", "#3987e5", "#e66767")


def current_theme() -> Theme:
    return DARK if ui_theme.is_dark() else LIGHT


def fmt(value: Decimal | float, unit: str = "", decimals: int = 0) -> str:
    text = f"{float(value):,.{decimals}f}".replace(",", " ")
    return f"{text} {unit}".strip()


def _short_month(label: str) -> str:
    """'2025-03' → '03/25' to keep a month axis readable."""
    if len(label) == 7 and label[4] == "-":
        return f"{label[5:]}/{label[2:4]}"
    return label


# Smallest category label size before giving up (Qt then elides the label to "…")
MIN_LABEL_POINTS = 6.0
# Room Qt needs around an axis label before it elides it: labels are text items with a 4 px
# document margin on each side (measured with QtCharts 6: elided below ~9 px of slack).
# Along a horizontal axis Qt also keeps a gap between neighbouring labels.
LABEL_MARGIN = 10.0
LABEL_MARGIN_ALONG = 20.0


class FittedChartView(QChartView):
    """Chart view that shrinks the category labels until every one of them fits.

    Qt elides a category label that is wider (vertical bars) or taller (horizontal bars) than
    the space of its bar, which with many bars or a large system font hides all of them.
    """

    def __init__(
        self, chart: QChart, axis: QBarCategoryAxis, categories: list[str], horizontal: bool
    ) -> None:
        super().__init__(chart)
        self._axis = axis
        self._categories = categories
        self._horizontal = horizontal
        # The plot area is final only after the chart's layout ran, not yet in resizeEvent
        chart.plotAreaChanged.connect(self.fit_labels)

    def fit_labels(self) -> None:
        if not self._categories:
            return
        plot = self.chart().plotArea()
        per = (plot.height() if self._horizontal else plot.width()) / len(self._categories)
        if per <= 0:
            return
        font = QFont(QApplication.font())
        base = font.pointSizeF() if font.pointSizeF() > 0 else 9.0  # -1 when the font is set in pixels
        size = base

        def fits(points: float, rotated: bool) -> bool:
            font.setPointSizeF(points)
            fm = QFontMetricsF(font)
            if self._horizontal or rotated:
                return fm.height() + LABEL_MARGIN <= per
            return max(fm.horizontalAdvance(c) for c in self._categories) + LABEL_MARGIN_ALONG <= per

        rotated = False
        while size > MIN_LABEL_POINTS and not fits(size, rotated):
            size -= 0.5
        if not self._horizontal and not fits(size, rotated):
            # Even the smallest text is too wide: turn the labels and fit their height instead
            rotated, size = True, base
            while size > MIN_LABEL_POINTS and not fits(size, rotated):
                size -= 0.5
        font.setPointSizeF(max(size, MIN_LABEL_POINTS))
        if self._axis.labelsFont() != font:
            self._axis.setLabelsFont(font)
        angle = -90 if rotated else 0
        if self._axis.labelsAngle() != angle:
            self._axis.setLabelsAngle(angle)


@dataclass(frozen=True)
class BarLayer:
    """One coloured layer of a stacked bar chart (a legend entry)."""

    label: str
    values: list[float]
    color: str


def stacked_chart(
    title: str,
    categories: list[str],
    layers: list[BarLayer],
    tooltip: Callable[[int], str],
    *,
    horizontal: bool = False,
    legend: bool = True,
) -> FittedChartView:
    """Stacked bars, one ``BarLayer`` per colour; ``tooltip(index)`` describes a hovered bar."""
    theme = current_theme()
    chart = QChart()
    if not categories or not any(v for layer in layers for v in layer.values):
        title += "\n" + _("žádná data za zvolené období")
    chart.setTitle(title)
    title_font = QFont()
    title_font.setBold(True)
    title_font.setPointSizeF(title_font.pointSizeF() + 1)
    chart.setTitleFont(title_font)
    chart.setTitleBrush(QColor(theme.ink))
    chart.setBackgroundBrush(QColor(theme.surface))
    chart.setBackgroundRoundness(10)  # same card look as the tiles and group boxes (ui/theme.py)
    chart.setBackgroundPen(QPen(QColor(ui_theme.current().border), 1))
    chart.setDropShadowEnabled(False)
    chart.setMargins(QMargins(6, 6, 6, 6))
    chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)
    # Axis numbers with Czech digit grouping ("100 000" instead of "100000")
    chart.setLocale(QLocale(QLocale.Language.Czech, QLocale.Country.CzechRepublic))
    chart.setLocalizeNumbers(True)

    series = QHorizontalStackedBarSeries() if horizontal else QStackedBarSeries()
    series.setBarWidth(0.6)
    for layer in layers:
        barset = QBarSet(layer.label)
        barset.append(layer.values)
        barset.setColor(QColor(layer.color))
        barset.setBorderColor(QColor(theme.surface))  # thin surface gap between adjacent bars
        series.append(barset)
    chart.addSeries(series)

    cat_axis = QBarCategoryAxis()
    cat_axis.append(categories)
    val_axis = QValueAxis()
    # Stacked: positive layers add up above zero, negative ones below
    tops = [sum(max(layer.values[i], 0.0) for layer in layers) for i in range(len(categories))]
    bottoms = [sum(min(layer.values[i], 0.0) for layer in layers) for i in range(len(categories))]
    low, high = min([0.0, *bottoms]), max([0.0, *tops])
    if low == high:
        high = 1.0
    val_axis.setRange(low, high)
    val_axis.applyNiceNumbers()
    val_axis.setLabelFormat("%.0f")
    val_axis.setLabelsVisible(high > 1 or low < 0)  # an empty chart would show '0 0 0 1 1 1'
    for axis in (cat_axis, val_axis):
        axis.setLabelsColor(QColor(theme.muted))
        axis.setLinePen(QPen(QColor(theme.baseline), 1))
        axis.setGridLinePen(QPen(QColor(theme.grid), 1))
    cat_axis.setGridLineVisible(False)
    if horizontal:
        chart.addAxis(val_axis, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(cat_axis, Qt.AlignmentFlag.AlignLeft)
    else:
        chart.addAxis(cat_axis, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(val_axis, Qt.AlignmentFlag.AlignLeft)
    series.attachAxis(cat_axis)
    series.attachAxis(val_axis)

    chart_legend = chart.legend()
    chart_legend.setVisible(legend)
    chart_legend.setAlignment(Qt.AlignmentFlag.AlignTop)
    chart_legend.setLabelColor(QColor(theme.secondary))

    def on_hover(state: bool, index: int, _barset: QBarSet) -> None:
        if state and 0 <= index < len(categories):
            QToolTip.showText(QCursor.pos(), tooltip(index))
        else:
            QToolTip.hideText()

    series.hovered.connect(on_hover)

    view = FittedChartView(chart, cat_axis, categories, horizontal)
    view.setRenderHint(QPainter.RenderHint.Antialiasing)
    view.setBackgroundBrush(QColor(ui_theme.current().window))  # behind the rounded card corners
    view.setFrameShape(QFrame.Shape.NoFrame)
    # Horizontal bars need room per category; grow with the system font so labels shrink less
    row = QFontMetricsF(QApplication.font()).height() + LABEL_MARGIN + 4
    legend_room = 30 if legend else 0
    view.setMinimumHeight(max(260, int(90 + legend_room + row * len(categories))) if horizontal else 260)
    return view


def bar_chart(
    title: str,
    data: Sequence[tuple[str, Decimal]],
    unit: str,
    *,
    horizontal: bool = False,
    diverging: bool = False,
    labels: tuple[str, str] | None = None,
    colors: tuple[str, str] | None = None,
) -> FittedChartView:
    """Bar chart of (category, value). ``diverging`` colours positive/negative bars apart
    (``labels`` and ``colors`` for the positive and the negative side)."""
    theme = current_theme()
    rows = list(reversed(data)) if horizontal else list(data)  # horizontal: first item on top
    values = [float(v) for _, v in rows]
    if diverging:
        # One layer per sign lets each bar take the colour of its sign
        positive, negative = labels or (_("Zisk"), _("Ztráta"))
        pos_color, neg_color = colors or (theme.positive, theme.negative)
        layers = [
            BarLayer(positive, [v if v >= 0 else 0.0 for v in values], pos_color),
            BarLayer(negative, [v if v < 0 else 0.0 for v in values], neg_color),
        ]
    else:
        layers = [BarLayer(title, values, theme.positive)]
    return stacked_chart(
        title,
        [_short_month(c) for c, _ in rows],
        layers,
        lambda i: f"{rows[i][0]}: {fmt(rows[i][1], unit)}",
        horizontal=horizontal,
        legend=diverging,  # one series → the title names it, no legend box
    )


def tax_impact_chart(title: str, before: Decimal, after: Decimal, unit: str) -> FittedChartView:
    """Tax without and with a sale: the common part grey, an increase yellow, a saving green.

    Status colours never carry the meaning alone: the legend names them and the tooltip and the
    text next to the chart give the amounts.
    """
    theme = current_theme()
    common = float(min(before, after))
    increase = float(max(after - before, Decimal(0)))
    saving = float(max(before - after, Decimal(0)))
    layers = [
        BarLayer(_("Daň"), [float(before), common], theme.muted),
        BarLayer(_("Zvýšení daně"), [0.0, increase], STATUS_WARNING),
        BarLayer(_("Úspora daně"), [0.0, saving], STATUS_GOOD),
    ]
    delta = after - before
    texts = [
        _("Bez prodeje: {tax}").format(tax=fmt(before, unit)),
        _("S prodejem: {tax} ({delta})").format(
            tax=fmt(after, unit), delta=("+" if delta > 0 else "") + fmt(delta, unit)
        ),
    ]
    return stacked_chart(title, [_("Bez prodeje"), _("S prodejem")], layers, lambda i: texts[i])


def tax_delta_chart(title: str, points: Sequence[tuple[str, Decimal, str]], unit: str) -> FittedChartView:
    """Extra tax (yellow) or saving (green) of a sale per day; points are (day, delta, why)."""
    values = [float(delta) for _, delta, _why in points]
    layers = [
        BarLayer(_("Zvýšení daně"), [v if v > 0 else 0.0 for v in values], STATUS_WARNING),
        BarLayer(_("Úspora daně"), [v if v < 0 else 0.0 for v in values], STATUS_GOOD),
    ]

    def tooltip(i: int) -> str:
        day, delta, why = points[i]
        return f"{day}: {'+' if delta > 0 else ''}{fmt(delta, unit)} ({why})"

    return stacked_chart(title, [day for day, _delta, _why in points], layers, tooltip)


def cash_flow_chart(
    title: str,
    deposits: Sequence[tuple[str, Decimal]],
    withdrawals: Sequence[tuple[str, Decimal]],
    unit: str,
) -> FittedChartView:
    """Deposits up (blue) and withdrawals down (red, negative) per period; the tooltip adds the net."""
    theme = current_theme()
    layers = [
        BarLayer(_("Vklady"), [float(v) for _p, v in deposits], theme.positive),
        BarLayer(_("Výběry"), [float(v) for _p, v in withdrawals], theme.negative),
    ]

    def tooltip(i: int) -> str:
        period, inflow = deposits[i]
        outflow = withdrawals[i][1]
        return _("{period}: vklady {deposits}, výběry {withdrawals}, čistě {net}").format(
            period=period,
            deposits=fmt(inflow, unit),
            withdrawals=fmt(outflow, unit),
            net=fmt(inflow + outflow, unit),
        )

    return stacked_chart(title, [_short_month(p) for p, _v in deposits], layers, tooltip)

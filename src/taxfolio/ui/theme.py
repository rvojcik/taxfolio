"""Application look: Fusion style + palette + one stylesheet, in a light and a dark variant.

Colours follow the chart palette (``charts.LIGHT`` / ``charts.DARK``): the same surfaces and inks,
blue as the accent. ``apply`` must run before any window is created; switching the appearance
rebuilds the main window (like switching the language) so charts and tiles pick up the new colours.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from importlib import resources

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QPushButton

from taxfolio.i18n import N_


class Appearance(StrEnum):
    SYSTEM = ""
    LIGHT = "light"
    DARK = "dark"


APPEARANCES = {  # translate on display
    Appearance.SYSTEM: N_("Podle systému"),
    Appearance.LIGHT: N_("Světlý"),
    Appearance.DARK: N_("Tmavý"),
}


@dataclass(frozen=True)
class UiColors:
    dark: bool
    window: str  # page background
    surface: str  # cards, tables, inputs
    surface_alt: str  # table headers, hovered rows, tab bar
    border: str
    ink: str
    secondary: str
    muted: str
    accent: str
    accent_hover: str
    accent_ink: str  # text on the accent
    selection: str  # selected rows (soft accent)
    positive_text: str  # gains in tables
    negative_text: str  # losses in tables


LIGHT = UiColors(
    dark=False,
    window="#f1f1ee",
    surface="#fcfcfb",
    surface_alt="#f6f6f3",
    border="#dddcd5",
    ink="#0b0b0b",
    secondary="#52514e",
    muted="#898781",
    accent="#2a78d6",
    accent_hover="#1f66bd",
    accent_ink="#ffffff",
    selection="#dbe8f8",
    positive_text="#006300",
    negative_text="#c42f2e",
)
DARK = UiColors(
    dark=True,
    window="#111110",
    surface="#1a1a19",
    surface_alt="#222220",
    border="#33332f",
    ink="#f0efec",
    secondary="#c3c2b7",
    muted="#898781",
    accent="#3987e5",
    accent_hover="#5398ea",
    accent_ink="#ffffff",
    selection="#1e3a5c",
    positive_text="#0ca30c",
    negative_text="#e66767",
)

# Settings-style section titles: space above each card and the gap between title and card (px)
GROUP_TITLE_GAP = 8
GROUP_TITLE_SPACE = 30

_current: UiColors = LIGHT


def current() -> UiColors:
    return _current


def is_dark() -> bool:
    return _current.dark


def system_is_dark() -> bool:
    hints = QGuiApplication.styleHints()
    return hints.colorScheme() == Qt.ColorScheme.Dark


def resolve(appearance: str) -> UiColors:
    if appearance == Appearance.DARK:
        return DARK
    if appearance == Appearance.LIGHT:
        return LIGHT
    return DARK if system_is_dark() else LIGHT


def apply(app: QApplication, appearance: str = Appearance.SYSTEM) -> UiColors:
    global _current
    _current = c = resolve(appearance)
    sheet = stylesheet(c)
    if app.styleSheet() == sheet:
        return c  # re-styling repolishes every widget – skip it when nothing changed (language switch)
    app.setStyle("Fusion")  # the same look on Linux, Windows and macOS; fully stylable
    app.setPalette(palette(c))
    app.setStyleSheet(sheet)
    return c


def palette(c: UiColors) -> QPalette:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: c.window,
        QPalette.ColorRole.WindowText: c.ink,
        QPalette.ColorRole.Base: c.surface,
        QPalette.ColorRole.AlternateBase: c.surface_alt,
        QPalette.ColorRole.Text: c.ink,
        QPalette.ColorRole.Button: c.surface,
        QPalette.ColorRole.ButtonText: c.ink,
        QPalette.ColorRole.ToolTipBase: c.surface,
        QPalette.ColorRole.ToolTipText: c.ink,
        QPalette.ColorRole.PlaceholderText: c.muted,
        QPalette.ColorRole.Highlight: c.selection,
        QPalette.ColorRole.HighlightedText: c.ink,
        QPalette.ColorRole.Link: c.accent,
        QPalette.ColorRole.Mid: c.border,
        QPalette.ColorRole.Midlight: c.surface_alt,
        QPalette.ColorRole.Dark: c.border,
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(c.muted))
    return p


def primary(button: QPushButton) -> QPushButton:
    """Mark the main action of a screen (accent-filled button)."""
    button.setProperty("primary", True)
    return button


def _icon(name: str) -> str:
    """Path of a packaged icon for ``url()`` in the stylesheet (forward slashes on every OS)."""
    return str(resources.files("taxfolio.resources").joinpath(name)).replace("\\", "/")


def stylesheet(c: UiColors) -> str:
    chevron = _icon("chevron-down-dark.svg" if c.dark else "chevron-down-light.svg")
    return f"""
QMainWindow, QDialog {{ background: {c.window}; }}
QWidget {{ color: {c.ink}; }}
QToolTip {{ background: {c.surface}; color: {c.ink}; border: 1px solid {c.border}; padding: 4px 6px; }}

/* top bar with the account / year selectors */
QToolBar {{ background: {c.surface}; border: none; border-bottom: 1px solid {c.border};
            padding: 6px 10px; spacing: 6px; }}
QToolBar QLabel {{ color: {c.secondary}; }}

/* tabs: flat, the selected one underlined in the accent */
QTabWidget::pane {{ border: none; border-top: 1px solid {c.border}; background: {c.window}; }}
QTabBar {{ background: {c.surface}; }}
QTabBar::tab {{ background: transparent; color: {c.secondary}; padding: 9px 16px; margin: 0;
                border: none; border-bottom: 2px solid transparent; }}
QTabBar::tab:hover {{ color: {c.ink}; background: {c.surface_alt}; }}
QTabBar::tab:selected {{ color: {c.accent}; border-bottom: 2px solid {c.accent}; font-weight: 600; }}

/* group boxes as cards */
/* the title sits above the card: margin-top = title line + gap (GROUP_TITLE_GAP) */
QGroupBox {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 10px;
             margin-top: {GROUP_TITLE_SPACE}px; padding: 12px 12px 10px 12px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 4px; top: 0px;
                    padding: 0 0 {GROUP_TITLE_GAP}px 0; color: {c.ink}; background: transparent; }}
QGroupBox QLabel, QGroupBox QCheckBox {{ font-weight: normal; }}

/* buttons */
QPushButton {{ background: {c.surface}; color: {c.ink}; border: 1px solid {c.border};
               border-radius: 7px; padding: 6px 14px; min-height: 20px; }}
QPushButton:hover {{ background: {c.surface_alt}; border-color: {c.muted}; }}
QPushButton:pressed {{ background: {c.border}; }}
QPushButton:disabled {{ color: {c.muted}; background: {c.surface_alt}; border-color: {c.border}; }}
QPushButton[primary="true"] {{ background: {c.accent}; color: {c.accent_ink}; border: 1px solid {c.accent};
                               font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: {c.accent_hover}; border-color: {c.accent_hover}; }}
QPushButton[primary="true"]:disabled {{ background: {c.border}; border-color: {c.border}; color: {c.muted}; }}

/* inputs */
QLineEdit, QComboBox, QDateEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
    background: {c.surface}; border: 1px solid {c.border}; border-radius: 7px;
    padding: 5px 8px; selection-background-color: {c.selection}; selection-color: {c.ink}; }}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {c.accent}; }}
QLineEdit:disabled, QComboBox:disabled {{ color: {c.muted}; background: {c.surface_alt}; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url({chevron}); width: 12px; height: 12px; }}
QComboBox {{ padding-right: 24px; }}
QComboBox QAbstractItemView {{ background: {c.surface}; border: 1px solid {c.border};
                               selection-background-color: {c.selection}; selection-color: {c.ink};
                               outline: none; padding: 4px; }}
QCheckBox {{ spacing: 8px; }}

/* tables */
QTableView, QTableWidget {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 8px;
                            gridline-color: {c.surface_alt}; selection-background-color: {c.selection};
                            selection-color: {c.ink}; alternate-background-color: {c.surface_alt}; }}
QTableView::item {{ padding: 2px 6px; }}
QTableView::item:hover {{ background: {c.surface_alt}; }}
QTableView::item:selected {{ background: {c.selection}; color: {c.ink}; }}
QHeaderView::section {{ background: {c.surface_alt}; color: {c.secondary}; border: none;
                        border-bottom: 1px solid {c.border}; border-right: 1px solid {c.border};
                        padding: 6px 8px; font-weight: 600; }}
QHeaderView::section:last {{ border-right: none; }}
QTableCornerButton::section {{ background: {c.surface_alt}; border: none; }}

/* slim scrollbars */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {c.border}; border-radius: 4px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: {c.muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* overview tiles */
QFrame#tile {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 10px; }}
QFrame#tile QLabel {{ background: transparent; }}
QLabel#tileCaption {{ color: {c.secondary}; }}
QLabel#tileDetail {{ color: {c.muted}; }}
"""

"""Coloured notices in the status bar: what the application is doing, how it ended.

A notice is a rounded, tinted label with an icon and a text (colour is never the only cue);
styled in ui/theme.py by its ``level`` property. Success and info notices fade away after a
while, warnings and errors stay until something newer replaces them.
"""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QWidget


class Level(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


ICONS = {Level.INFO: "ℹ", Level.SUCCESS: "✓", Level.WARNING: "⚠", Level.ERROR: "✕"}
BUSY_ICON = "⟳"
# How long a notice stays (ms); None = until replaced
DEFAULT_TIMEOUT = {Level.INFO: 8_000, Level.SUCCESS: 8_000, Level.WARNING: None, Level.ERROR: None}


class Notice(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("notice")
        self.setWordWrap(False)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clear_notice)
        self.level: Level | None = None
        self.hide()

    def show_notice(
        self, text: str, level: Level = Level.INFO, timeout: int | None = -1, busy: bool = False
    ) -> None:
        """``timeout``: ms until it disappears, None to keep it, -1 for the level's default."""
        self.level = level
        self.setProperty("level", level.value)
        self.style().unpolish(self)  # re-apply the stylesheet for the new level
        self.style().polish(self)
        self.setText(f"{BUSY_ICON if busy else ICONS[level]}  {text}")
        self.setToolTip(text)
        self.show()
        self._timer.stop()
        duration = DEFAULT_TIMEOUT[level] if timeout == -1 else timeout
        if duration is not None and not busy:
            self._timer.start(duration)

    def clear_notice(self) -> None:
        self._timer.stop()
        self.level = None
        self.clear()
        self.hide()

    def message(self) -> str:
        """The text without the icon (tests, accessibility)."""
        return self.text().split("  ", 1)[-1] if self.text() else ""

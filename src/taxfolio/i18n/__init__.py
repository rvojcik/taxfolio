"""Minimal translation layer.

Czech is the source language: texts in the code are Czech and wrapped in ``_()`` at the point
where they are shown. ``N_()`` marks texts stored in module-level tables (translated later, at
display time, with ``_()``). Catalogs map the Czech text to its translation; a missing entry falls
back to Czech. ``tools/i18n_extract.py`` lists every marked text and the test-suite checks that
each language has all of them with the same ``{placeholders}``.
"""

from __future__ import annotations

import locale
from importlib import import_module

LANGUAGES = {"cs": "Čeština", "sk": "Slovenčina", "en": "English"}
SOURCE_LANGUAGE = "cs"

_current = SOURCE_LANGUAGE
_catalog: dict[str, str] = {}


def catalog(code: str) -> dict[str, str]:
    if code == SOURCE_LANGUAGE:
        return {}
    module = import_module(f"taxfolio.i18n.{code}")
    data: dict[str, str] = module.CATALOG
    return data


def set_language(code: str) -> None:
    global _current, _catalog
    if code not in LANGUAGES:
        code = SOURCE_LANGUAGE
    _current, _catalog = code, catalog(code)


def current_language() -> str:
    return _current


def system_language() -> str:
    """Best guess from the OS locale; English unless the system is Czech or Slovak."""
    name = (locale.getlocale()[0] or "").lower()
    for code in ("cs", "sk"):
        if name.startswith(code):
            return code
    return "en"


def _(text: str) -> str:
    return _catalog.get(text, text)


def N_(text: str) -> str:  # noqa: N802 – conventional gettext name
    """Mark a text for extraction without translating it yet."""
    return text

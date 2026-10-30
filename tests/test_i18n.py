import re
import sys
from pathlib import Path

import pytest

from taxfolio.i18n import LANGUAGES, SOURCE_LANGUAGE, _, catalog, current_language, set_language

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from i18n_extract import extract  # noqa: E402

PLACEHOLDER = re.compile(r"\{[a-z_]+\}")
TEXTS, PROBLEMS = extract()


@pytest.fixture(autouse=True)
def restore_language():  # noqa: ANN201
    yield
    set_language(SOURCE_LANGUAGE)


def test_extraction_finds_texts_without_problems() -> None:
    assert len(TEXTS) > 300
    assert PROBLEMS == []


@pytest.mark.parametrize("code", [c for c in LANGUAGES if c != SOURCE_LANGUAGE])
def test_catalog_is_complete_and_consistent(code: str) -> None:
    cat = catalog(code)
    missing = [t for t in TEXTS if t not in cat]
    stale = [t for t in cat if t not in TEXTS]
    assert missing == [], f"{code}: missing translations"
    assert stale == [], f"{code}: translations of texts no longer in the code"
    for source, translated in cat.items():
        assert sorted(PLACEHOLDER.findall(source)) == sorted(PLACEHOLDER.findall(translated)), source
        assert translated.strip(), source


def test_switching_language() -> None:
    assert _("Přehled") == "Přehled"
    set_language("en")
    assert current_language() == "en" and _("Přehled") == "Overview"
    set_language("sk")
    assert _("Přehled") == "Prehľad"
    assert _("text bez překladu") == "text bez překladu"  # falls back to the source
    set_language("xx")
    assert current_language() == SOURCE_LANGUAGE

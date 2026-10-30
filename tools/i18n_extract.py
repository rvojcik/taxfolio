"""List all translatable texts: string arguments of ``_()`` / ``N_()`` calls in src/taxfolio.

Usage: python tools/i18n_extract.py            → prints the texts (one repr per line)
       python tools/i18n_extract.py --missing sk → texts without a Slovak translation
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "taxfolio"
# Helpers that translate each of their string arguments (``_headers("Datum", "Symbol")``)
MULTI_ARG_HELPERS = {"_headers"}


def extract(root: Path = SRC) -> tuple[dict[str, list[str]], list[str]]:
    """Return {text: [locations]} and a list of problems (non-literal arguments)."""
    texts: dict[str, list[str]] = {}
    problems: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if "i18n" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            where = f"{path.relative_to(root.parent)}:{node.lineno}"
            if node.func.id in MULTI_ARG_HELPERS:  # every literal argument is a text, e.g. table headers
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        texts.setdefault(arg.value, []).append(where)
                continue
            if node.func.id not in ("_", "N_"):
                continue
            arg = node.args[0] if len(node.args) == 1 else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                texts.setdefault(arg.value, []).append(where)
            elif node.func.id == "N_" or isinstance(arg, (ast.JoinedStr, ast.BinOp)) or arg is None:
                # an f-string or concatenation can never match a catalog entry
                problems.append(f"{where}: {node.func.id}() needs one plain string literal")
            # _(variable) translates a text marked with N_() elsewhere – fine
    return texts, problems


def main() -> int:
    texts, problems = extract()
    for p in problems:
        print("PROBLEM", p, file=sys.stderr)
    if len(sys.argv) == 3 and sys.argv[1] == "--missing":
        sys.path.insert(0, str(SRC.parent))
        from taxfolio.i18n import catalog

        have = catalog(sys.argv[2])
        for text in texts:
            if text not in have:
                print(repr(text))
        return 0
    for text in texts:
        print(repr(text))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

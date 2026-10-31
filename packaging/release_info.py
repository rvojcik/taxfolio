"""Release helpers for CI.

python packaging/release_info.py check-tag v1.2.0   # or 1.2.0; fails unless pyproject.toml says 1.2.0
python packaging/release_info.py notes 1.2.0        # that version's section of CHANGELOG.md
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def project_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def notes(version: str) -> str:
    """Text under '## [<version>]' up to the next '## ' heading."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## \[?{re.escape(version)}\]?[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match:
        raise SystemExit(f"CHANGELOG.md has no section for {version}")
    return match.group(1).strip() + "\n"


def main() -> None:
    command, value = sys.argv[1], sys.argv[2]
    if command == "check-tag":
        expected = f"v{project_version()}"
        if value not in (expected, expected[1:]):  # v0.1.0 or 0.1.0
            raise SystemExit(
                f"Tag {value} does not match pyproject.toml version ({expected}). Bump the version first."
            )
        print(f"Tag {value} matches the project version.")
    elif command == "notes":
        sys.stdout.write(notes(value))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()

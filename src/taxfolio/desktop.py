"""Application launcher entry: a freedesktop ``.desktop`` file and icon (Linux).

``taxfolio desktop install`` writes them into the user's data directory, so the app shows up in
the GNOME / KDE / XFCE launcher. Windows and macOS get their entries from an installer instead.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

APP_ID = "taxfolio"  # also QGuiApplication.desktopFileName, so windows group under the launcher icon
LEGACY_APP_ID = "ibkr-tax"  # launcher of versions before the rename to Taxfolio
ICON_RESOURCE = "taxfolio.svg"


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def desktop_file() -> Path:
    return data_home() / "applications" / f"{APP_ID}.desktop"


def icon_file() -> Path:
    return data_home() / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"


def gui_command() -> str:
    """The ``taxfolio-gui`` script of the environment this code runs from."""
    script = Path(sys.executable).parent / ("taxfolio-gui.exe" if os.name == "nt" else "taxfolio-gui")
    found = str(script) if script.exists() else shutil.which("taxfolio-gui")
    if not found:
        raise FileNotFoundError("Příkaz taxfolio-gui nenalezen – nainstalujte aplikaci: uv tool install .")
    return found


def desktop_entry(command: str, icon: Path) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Taxfolio\n"
        "GenericName=Obchodní deník a daně\n"
        "Comment=Obchodní deník a podklady k daňovému přiznání v ČR a SR (IBKR, XTB)\n"
        "Comment[en]=Trading journal and Czech/Slovak tax reports (IBKR, XTB)\n"
        "Comment[sk]=Obchodný denník a podklady k daňovému priznaniu v ČR a SR (IBKR, XTB)\n"
        f'Exec="{command}"\n'
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=Office;Finance;\n"
        "Keywords=IBKR;XTB;tax;daně;dane;portfolio;\n"
        f"StartupWMClass={APP_ID}\n"
    )


def install() -> list[Path]:
    if not sys.platform.startswith("linux"):
        raise OSError("Zástupce v nabídce aplikací se zatím vytváří jen na Linuxu.")
    icon = icon_file()
    icon.parent.mkdir(parents=True, exist_ok=True)
    icon.write_bytes(resources.files("taxfolio.resources").joinpath(ICON_RESOURCE).read_bytes())
    entry = desktop_file()
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(desktop_entry(gui_command(), icon), encoding="utf-8")
    entry.chmod(0o755)
    _remove_legacy()  # the launcher of the old name would start a version that no longer exists
    _refresh(entry.parent)
    return [entry, icon]


def uninstall() -> list[Path]:
    removed = [p for p in (desktop_file(), icon_file()) if p.exists()]
    for p in removed:
        p.unlink()
    removed += _remove_legacy()
    _refresh(desktop_file().parent)
    return removed


def _remove_legacy() -> list[Path]:
    legacy = [
        data_home() / "applications" / f"{LEGACY_APP_ID}.desktop",
        data_home() / "icons" / "hicolor" / "scalable" / "apps" / f"{LEGACY_APP_ID}.svg",
    ]
    removed = [p for p in legacy if p.exists()]
    for p in removed:
        p.unlink()
    return removed


def _refresh(applications: Path) -> None:
    # Optional: launchers also notice the change on their own after a moment
    if shutil.which("update-desktop-database") and applications.exists():
        subprocess.run(["update-desktop-database", str(applications)], check=False, capture_output=True)

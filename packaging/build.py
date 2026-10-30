"""Build the desktop application and its installer for the current operating system.

    uv run --group build python packaging/build.py            # PyInstaller bundle + installer
    uv run --group build python packaging/build.py --bundle-only

Output in dist/:
  Linux    Taxfolio-<version>-x86_64.AppImage   (needs appimagetool, downloaded if missing)
  Windows  Taxfolio-<version>-Setup.exe         (needs Inno Setup's iscc on PATH)
  macOS    Taxfolio-<version>-macOS.dmg         (hdiutil, part of macOS)

Used by .github/workflows/release.yml; runs the same locally.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
APP_NAME = "Taxfolio"  # file names: ASCII only
DISPLAY_NAME = "Taxfolio"
BUNDLE_ID = "io.github.rvojcik.taxfolio"
ICON_SVG = ROOT / "src" / "taxfolio" / "resources" / "taxfolio.svg"
APPIMAGETOOL_URL = (
    "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
)


def version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def run(*cmd: str | Path, **kwargs: object) -> None:
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kwargs)  # type: ignore[arg-type]


# ------------------------------------------------------------------ icons


def render_icons() -> dict[str, Path]:
    """PNG / ICO / ICNS from the SVG icon, rendered with Qt (no extra dependencies)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    _app = QGuiApplication.instance() or QGuiApplication([])
    out = BUILD / "icons"
    out.mkdir(parents=True, exist_ok=True)
    renderer = QSvgRenderer(str(ICON_SVG))

    def png(size: int, path: Path) -> Path:
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        if not image.save(str(path)):
            raise RuntimeError(f"cannot write {path}")
        return path

    icons = {"png": png(256, out / "taxfolio.png")}
    if sys.platform == "win32":
        icons["ico"] = png(256, out / "taxfolio.ico")  # Qt's ico plugin writes .ico by extension
    if sys.platform == "darwin":
        iconset = out / "taxfolio.iconset"
        iconset.mkdir(exist_ok=True)
        for size in (16, 32, 128, 256, 512):
            png(size, iconset / f"icon_{size}x{size}.png")
            png(size * 2, iconset / f"icon_{size}x{size}@2x.png")
        run("iconutil", "-c", "icns", iconset, "-o", out / "taxfolio.icns")
        icons["icns"] = out / "taxfolio.icns"
    return icons


# ------------------------------------------------------------------ PyInstaller


def bundle(icons: dict[str, Path]) -> Path:
    """One-folder bundle (Qt stays a separate shared library – LGPL friendly, fast start)."""
    args: list[str | Path] = [
        sys.executable,
        "-m",
        "PyInstaller",
        PACKAGING / "launcher.py",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        APP_NAME,
        "--distpath",
        DIST,
        "--workpath",
        BUILD / "pyinstaller",
        "--specpath",
        BUILD,
        "--collect-data",
        "taxfolio",  # tax rules (YAML) and icons
        "--collect-submodules",
        "taxfolio",  # i18n catalogs, lazily imported modules
        "--copy-metadata",
        "taxfolio",  # the version shown in the app and used by the update check
        "--copy-metadata",
        "keyring",  # keyring finds its backends through package metadata
        "--collect-submodules",
        "keyring.backends",
        "--osx-bundle-identifier",
        BUNDLE_ID,
    ]
    if "ico" in icons:
        args += ["--icon", icons["ico"]]
    if "icns" in icons:
        args += ["--icon", icons["icns"]]
    run(*args, cwd=ROOT)
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        source = ROOT / name if (ROOT / name).exists() else PACKAGING / name
        if source.exists():
            target = DIST / (f"{APP_NAME}.app/Contents/Resources" if sys.platform == "darwin" else APP_NAME)
            shutil.copy(source, target / name)
    return DIST / (f"{APP_NAME}.app" if sys.platform == "darwin" else APP_NAME)


# ------------------------------------------------------------------ installers


def appimage(bundle_dir: Path, icons: dict[str, Path]) -> Path:
    appdir = BUILD / f"{APP_NAME}.AppDir"
    shutil.rmtree(appdir, ignore_errors=True)
    shutil.copytree(bundle_dir, appdir / "usr" / "lib" / APP_NAME)
    (appdir / "AppRun").write_text(
        '#!/bin/sh\nHERE="$(dirname "$(readlink -f "$0")")"\n'
        f'exec "$HERE/usr/lib/{APP_NAME}/{APP_NAME}" "$@"\n'
    )
    (appdir / "AppRun").chmod(0o755)
    shutil.copy(icons["png"], appdir / "taxfolio.png")
    (appdir / "taxfolio.desktop").write_text(
        "[Desktop Entry]\nType=Application\n"
        f"Name={DISPLAY_NAME}\nExec={APP_NAME}\nIcon=taxfolio\nCategories=Office;Finance;\n"
        "Comment=Trading journal and Czech/Slovak tax reports (IBKR, XTB)\nStartupWMClass=taxfolio\n"
    )
    tool = shutil.which("appimagetool") or _download_appimagetool()
    target = DIST / f"{APP_NAME}-{version()}-x86_64.AppImage"
    env = {**os.environ, "ARCH": "x86_64", "APPIMAGE_EXTRACT_AND_RUN": "1"}  # no FUSE needed in CI
    run(tool, "--no-appstream", appdir, target, env=env)
    return target


def _download_appimagetool() -> str:
    tool = BUILD / "appimagetool"
    if not tool.exists():
        print("downloading appimagetool …", flush=True)
        urllib.request.urlretrieve(APPIMAGETOOL_URL, tool)  # noqa: S310 – fixed https URL
        tool.chmod(0o755)
    return str(tool)


def windows_installer(icons: dict[str, Path]) -> Path:
    iscc = shutil.which("iscc") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    run(
        iscc,
        f"/DAppVersion={version()}",
        f"/DAppName={APP_NAME}",
        f"/DDisplayName={DISPLAY_NAME}",
        f"/DSourceDir={DIST / APP_NAME}",
        f"/DOutputDir={DIST}",
        f"/DIconFile={icons['ico']}",
        PACKAGING / "windows" / "installer.iss",
    )
    return DIST / f"{APP_NAME}-{version()}-Setup.exe"


def macos_dmg(app: Path) -> Path:
    staging = BUILD / "dmg"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    shutil.copytree(app, staging / app.name, symlinks=True)
    (staging / "Applications").symlink_to("/Applications")
    target = DIST / f"{APP_NAME}-{version()}-macOS.dmg"
    target.unlink(missing_ok=True)
    run("hdiutil", "create", "-volname", APP_NAME, "-srcfolder", staging, "-ov", "-format", "UDZO", target)
    return target


def main() -> None:
    # Windows consoles default to a legacy code page that cannot print "Daně"
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--bundle-only", action="store_true", help="only the PyInstaller bundle, no installer"
    )
    args = parser.parse_args()
    print(f"{DISPLAY_NAME} {version()} – {platform.system()} {platform.machine()}", flush=True)
    icons = render_icons()
    built = bundle(icons)
    if not args.bundle_only:
        if sys.platform.startswith("linux"):
            built = appimage(built, icons)
        elif sys.platform == "win32":
            built = windows_installer(icons)
        elif sys.platform == "darwin":
            built = macos_dmg(built)
    print(f"Built: {built}")


if __name__ == "__main__":
    main()

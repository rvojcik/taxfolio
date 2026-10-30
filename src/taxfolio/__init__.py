"""IBKR portfolio journal and Czech / Slovak tax analyzer."""

from importlib.metadata import PackageNotFoundError, version

try:
    # The single source of the version is pyproject.toml; releases are tagged v<version>.
    __version__ = version("taxfolio")
except PackageNotFoundError:  # running from a source tree without installing
    __version__ = "0.0.0"

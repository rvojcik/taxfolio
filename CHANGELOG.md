# Changelog

Version numbers follow [Semantic Versioning](https://semver.org/): MAJOR.MINOR.PATCH. A release is
the tag `v<version>`; the version itself lives only in `pyproject.toml`.

## [0.1.1] – 2026-10-31

Minor fixes, testing new version notification

- workflow and new version changes

## [0.1.0] – 2026-10-30

First public version.

- Import from Interactive Brokers (Flex Query XML, Activity Statement, Dividend Report, FX Income
  Worksheet, Flex Web Service) and XTB (cash operations CSV / XLSX).
- Data sources with one-click update for a chosen period; stoppable, runs in the background.
- Trading journal with stop-loss / take-profit detection, FIFO realisation checked against IBKR.
- Czech and Slovak tax documents (tax years 2021–2026): time tests, 100 000 Kč limit, 500 € exemption,
  dividends with foreign-tax credit, estimate at 15 % and 23 %, PDF / XLSX export.
- “Tax-free to sell” view, sale simulator with charts.
- Overview dashboard, light and dark appearance, Czech / Slovak / English.
- Automatic check for new versions.

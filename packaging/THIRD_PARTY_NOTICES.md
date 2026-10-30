# Third-party software

The application bundles these libraries. Their licences apply to their parts of the package.

| Component | Licence | Source |
|---|---|---|
| Qt 6 / PySide6 (Qt for Python) | LGPL-3.0 | https://www.qt.io/qt-for-python, https://code.qt.io |
| Python | PSF License | https://www.python.org |
| SQLAlchemy | MIT | https://www.sqlalchemy.org |
| PyYAML | MIT | https://pyyaml.org |
| openpyxl | MIT | https://openpyxl.readthedocs.io |
| keyring | MIT | https://github.com/jaraco/keyring |
| platformdirs | MIT | https://github.com/tox-dev/platformdirs |

Qt is distributed as separate shared libraries (not linked statically) inside the application
folder, so it can be replaced by a compatible build, as the LGPL requires. The Qt source code is
available from https://download.qt.io/official_releases/qt/.

Exchange rates are downloaded from the Czech National Bank (cnb.cz) and the European Central Bank
(ecb.europa.eu); statements from Interactive Brokers through its Flex Web Service.

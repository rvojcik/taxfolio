"""Smoke tests of the desktop UI (offscreen): values coming from Qt widgets reach the services intact."""

import os
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from taxfolio.fx.converter import RateSource  # noqa: E402
from taxfolio.fx.sources import CNB, ECB, RateRow  # noqa: E402
from taxfolio.services import import_service, rates_service  # noqa: E402
from taxfolio.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    return app


def _cnb_two_level(year: int) -> list[RateRow]:
    """USD at 20 Kč in the first half of the year and 25 Kč in the second → daily ≠ unified."""
    out, d = [], date(year, 1, 1)
    while d.year == year:
        out.append(RateRow(CNB, "USD", d, Decimal(20 if d.month <= 6 else 25)))
        d += timedelta(days=1)
    return out


def _ecb_flat(years: set[int]) -> list[RateRow]:
    out = []
    for y in years:
        d = date(y, 1, 1)
        while d.year == y:
            out.append(RateRow(ECB, "USD", d, Decimal("1.1")))
            d += timedelta(days=1)
    return out


@pytest.fixture
def window(qapp: QApplication, engine: Engine, fixtures: Path) -> Iterator[MainWindow]:
    import_service.import_file(engine, fixtures / "flex_2025.xml")
    rates_service.ensure_rates(
        engine, [2025, date.today().year], fetch_cnb=_cnb_two_level, fetch_ecb_years=_ecb_flat
    )
    w = MainWindow(engine)
    w._year.setCurrentIndex(w._year.findData(2025))
    yield w
    w.close()


def _set_rate(window: MainWindow, target: str, currency: str, source: RateSource, fixed: str = "") -> None:
    """Change one rate rule through the settings table and save, as a user would."""
    table = window._settings._tables[target]
    row = next(i for i, (ccy, _, _) in enumerate(table._rows) if ccy == currency)
    _, combo, fixed_edit = table._rows[row]
    combo.setCurrentIndex(combo.findData(source.value))
    fixed_edit.setText(fixed)
    window._settings._save()


def _usd_sale(window: MainWindow):  # noqa: ANN202
    cz = window._tax.cz
    cz.refresh()  # direct call: exceptions in signal handlers would only be printed
    (sale,) = cz._sales._rows
    return sale


def test_czech_tax_follows_rate_source_from_settings(window: MainWindow) -> None:
    # Sale of 480 USD on 2.9. → ČNB daily 25 Kč; unified 2025 = (6×20 + 6×25)/12 = 22.50 Kč
    assert _usd_sale(window).row.gross_proceeds_czk == Decimal(480) * 25
    assert "ČNB – denní kurz" in window._tax.cz._rates.text()

    _set_rate(window, "CZK", "USD", RateSource.GFR_ANNUAL)
    assert _usd_sale(window).row.gross_proceeds_czk == Decimal(480) * Decimal("22.50")
    doc = window._tax.cz._document
    assert doc is not None and "Jednotný kurz" in doc.subtitle

    _set_rate(window, "CZK", "USD", RateSource.FIXED, "21,5")
    assert _usd_sale(window).row.gross_proceeds_czk == Decimal(480) * Decimal("21.5")
    assert any("není podle zákona přípustný" in line for line in window._tax.cz._warnings.text().splitlines())


def test_settings_preview_shows_value_of_selected_source(window: MainWindow) -> None:
    table = window._settings._tables["CZK"]
    row = next(i for i, (ccy, _, _) in enumerate(table._rows) if ccy == "USD")
    _, combo, fixed = table._rows[row]
    preview, legal = table.cellWidget(row, 3), table.cellWidget(row, 4)
    combo.setCurrentIndex(combo.findData(RateSource.CNB_DAILY.value))
    assert "1 USD = " in preview.text() and "CZK" in preview.text() and "✔" in legal.text()
    combo.setCurrentIndex(combo.findData(RateSource.ECB_DAILY.value))
    assert "⚠" in legal.text()
    combo.setCurrentIndex(combo.findData(RateSource.FIXED.value))
    assert fixed.isEnabled()
    fixed.setText("23")
    assert "23,0000 CZK (pevně)" in preview.text()
    fixed.setText("abc")
    assert "⚠" in preview.text()


def test_tax_tab_switches_country_and_follows_default(window: MainWindow) -> None:
    tax = window._tax
    assert tax.country == "CZ"
    tax.set_country("SK")
    assert tax._stack.currentWidget() is tax.sk and tax.sk._document is not None
    window._settings._country.setCurrentIndex(window._settings._country.findData("SK"))
    window._settings._save()
    tax.set_country("CZ")
    tax.apply_settings()
    assert tax.country == "SK"


def test_realized_and_simulator_use_settings(window: MainWindow) -> None:
    _set_rate(window, "CZK", "USD", RateSource.FIXED, "20")
    realized = window._realized
    realized.refresh()
    (row,) = realized._model._rows
    assert row.proceeds_czk == row.match.proceeds * 20
    assert "pevný 20" in realized._rates.text()
    sim = window._simulator
    sim.refresh()
    sim._run()
    assert sim._lots.rowCount() == 1 and "⚠" not in sim._result.text()


def test_all_tabs_render_for_every_year_choice(window: MainWindow) -> None:
    for index in range(window._year.count()):
        window._year.setCurrentIndex(index)
        for view in (window._journal, window._realized, window._tax.cz, window._tax.sk):
            view.refresh()


def test_overview_renders_in_every_currency(window: MainWindow, qapp: QApplication) -> None:
    view = window._overview
    for index in range(view._currency.count()):
        view._currency.setCurrentIndex(index)
        view.refresh()
        qapp.processEvents()
        assert view._charts.count() == 7  # 6 charts + the company table
        assert view._tiles["realized"]._value.text().endswith(view._currency.currentText())


def test_sources_in_settings_and_update(
    window: MainWindow, fixtures: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QDialog

    from taxfolio.services import flex_sync, secrets
    from taxfolio.services.sources import SourceType, load_sources
    from taxfolio.ui.import_view import SourcesWorker
    from taxfolio.ui.sources_view import SourceDialog

    # Settings → Data sources: add an IBKR source through the dialog
    box = window._settings.sources
    dialog = SourceDialog(box)
    dialog._type.setCurrentIndex(dialog._type.findData(SourceType.IBKR_FLEX.value))
    dialog._name.setText("IBKR hlavní")
    dialog._inputs["query_id"].setText("123456")
    dialog._inputs["token"].setText("SECRET")
    dialog._accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    box._store(dialog.result_source)
    (ibkr,) = load_sources(window._engine)
    assert ibkr.settings == {"query_id": "123456"}  # the token is not in the database
    assert secrets.get_secret(ibkr.id, "token") == "SECRET" and ibkr.missing() == []
    assert "✔" in box._table.item(0, 2).text()

    # the Import tab offers it right away
    imp = window._import
    assert imp._source.findData(ibkr.id) >= 0
    current = date.today().year
    assert imp._flex_period.currentData() == f"{current}-{current}"  # current year by default
    assert imp._flex_period.findData("query") >= 0 and imp._flex_period.findData("2025-2025") >= 0
    imp._flex_period.setCurrentIndex(imp._flex_period.findData("2025-2025"))
    imp.refresh()
    assert imp._flex_period.currentData() == "2025-2025"  # the choice survives a refresh

    statement = fixtures / "flex_2025.xml"
    calls: list[tuple[str, str, object]] = []

    def download(token: str, query_id: str, period: object, **_kw: object) -> list[Path]:
        calls.append((token, query_id, period))
        return [statement]

    monkeypatch.setattr(flex_sync, "download_statements", download)
    worker = SourcesWorker(load_sources(window._engine), imp._period(), set())
    got: list[list[object]] = []
    worker.finished.connect(got.append)
    worker.run()  # synchronously; the thread wiring only moves this call off the UI thread
    assert calls == [("SECRET", "123456", flex_sync.years_period(2025, 2025))]
    imp._sources_fetched(got[0])
    assert "IBKR hlavní" in imp._log.toPlainText() and "OK" in imp._log.toPlainText()


@pytest.mark.parametrize("code", ["en", "sk"])
def test_every_tab_renders_in_language(engine: Engine, fixtures: Path, qapp: QApplication, code: str) -> None:
    from taxfolio.i18n import SOURCE_LANGUAGE, set_language

    import_service.import_file(engine, fixtures / "flex_2025.xml")
    set_language(code)
    try:
        w = MainWindow(engine)
        w._year.setCurrentIndex(w._year.findData(2025))
        for view in (w._overview, w._journal, w._realized, w._tax.cz, w._tax.sk, w._simulator, w._settings):
            view.refresh()
        w._tax.cz.refresh()
        expected = {"en": ("Overview", "Taxes"), "sk": ("Prehľad", "Dane")}[code]
        assert w._tabs.tabText(0) == expected[0] and w._tabs.tabText(3) == expected[1]
        assert w._tax.cz._document is not None
        w.close()
    finally:
        set_language(SOURCE_LANGUAGE)


def test_language_switch_rebuilds_window(engine: Engine, fixtures: Path, qapp: QApplication) -> None:
    from taxfolio.app import Application
    from taxfolio.i18n import SOURCE_LANGUAGE, set_language
    from taxfolio.services.settings import AppSettings, save_settings

    import_service.import_file(engine, fixtures / "flex_2025.xml")
    save_settings(engine, AppSettings(language="cs"))  # otherwise the OS language decides
    application = Application(engine)
    try:
        first = application.window
        assert first is not None and first._tabs.tabText(0) == "Přehled"
        first._tabs.setCurrentWidget(first._settings)
        settings = first._settings
        settings._language.setCurrentIndex(settings._language.findData("en"))
        settings._save()
        second = application.window
        assert second is not None and second is not first
        assert second._tabs.tabText(0) == "Overview"
        assert second._tabs.currentWidget() is second._settings  # stays on the same tab
        second.close()
    finally:
        set_language(SOURCE_LANGUAGE)


def test_overview_company_table_survives_refresh(window: MainWindow, qapp: QApplication) -> None:
    view = window._overview
    for _round in range(3):  # the charts are rebuilt each time; the table must stay alive
        view.refresh()
        qapp.processEvents()
    assert view._companies.rowCount() == 1 and view._charts.count() == 7
    assert view._share(view._companies._rows[0]) == "100.0%"


def test_chart_labels_shrink_to_fit(qapp: QApplication) -> None:
    from PySide6.QtGui import QFontMetricsF

    from taxfolio.ui.charts import LABEL_MARGIN, bar_chart

    data = [(f"SYMBOL{i}", Decimal(i + 1)) for i in range(11)]
    view = bar_chart("t", data, "CZK", horizontal=True)
    view.setMinimumHeight(0)
    view.resize(400, 260)  # far less than one text line per bar at the default size
    view.show()
    qapp.processEvents()
    per = view.chart().plotArea().height() / len(data)
    assert QFontMetricsF(view._axis.labelsFont()).height() + LABEL_MARGIN <= per + 0.01 or (
        view._axis.labelsFont().pointSizeF() == 6.0
    )
    assert view._axis.labelsFont().pointSizeF() < qapp.font().pointSizeF()

    months = [(f"2025-{m:02d}", Decimal(m)) for m in range(1, 13)] * 2
    narrow = bar_chart("t", months, "CZK")
    narrow.resize(260, 260)
    narrow.show()
    qapp.processEvents()
    assert narrow._axis.labelsAngle() == -90  # too narrow even for small text → vertical labels
    view.close()
    narrow.close()


def test_tax_impact_chart_colours_increase_and_saving(qapp: QApplication) -> None:
    from PySide6.QtCharts import QStackedBarSeries

    from taxfolio.ui.charts import STATUS_GOOD, STATUS_WARNING, tax_delta_chart, tax_impact_chart

    def layers(view) -> dict[str, list[float]]:  # type: ignore[no-untyped-def]
        (series,) = view.chart().series()
        assert isinstance(series, QStackedBarSeries)
        return {s.color().name(): [s.at(i) for i in range(s.count())] for s in series.barSets()}

    up = layers(tax_impact_chart("t", Decimal(100), Decimal(130), "Kč"))
    assert up[STATUS_WARNING] == [0, 30] and up[STATUS_GOOD] == [0, 0]
    down = layers(tax_impact_chart("t", Decimal(100), Decimal(70), "Kč"))
    assert down[STATUS_GOOD] == [0, 30] and down[STATUS_WARNING] == [0, 0]
    timeline = layers(tax_delta_chart("t", [("a", Decimal(5), ""), ("b", Decimal(-2), "")], "€"))
    assert timeline[STATUS_WARNING] == [5, 0] and timeline[STATUS_GOOD] == [0, -2]


def test_desktop_entry_install_and_uninstall(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from taxfolio import desktop

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    monkeypatch.setattr(desktop, "gui_command", lambda: "/opt/bin/taxfolio-gui")
    entry, icon = desktop.install()
    text = entry.read_text(encoding="utf-8")
    assert 'Exec="/opt/bin/taxfolio-gui"' in text and f"Icon={icon}" in text
    assert icon.read_bytes().startswith(b"<svg")
    assert desktop.uninstall() == [entry, icon] and not entry.exists()


def test_app_icon_loads(qapp: QApplication) -> None:
    from taxfolio.app import app_icon

    assert not app_icon().isNull()


def test_delete_several_imports(window: MainWindow, fixtures: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtWidgets import QMessageBox

    from taxfolio.services import queries

    imp = window._import
    imp.import_paths([fixtures / "dividends_2025.csv"])
    before = queries.list_batches(window._engine)
    assert len(before) >= 2
    selection = imp._table.selectionModel()
    for row in (0, 1):
        selection.select(
            imp._model.index(row, 0),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )
    assert imp._undo_btn.isEnabled() and "(2)" in imp._undo_btn.text()
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes)
    imp._undo_selected()
    assert len(queries.list_batches(window._engine)) == len(before) - 2
    assert not imp._undo_btn.isEnabled()


def test_appearance_switch_rebuilds_window_in_dark(
    engine: Engine, fixtures: Path, qapp: QApplication
) -> None:
    from taxfolio.app import Application
    from taxfolio.services.settings import AppSettings, load_settings, save_settings
    from taxfolio.ui import theme
    from taxfolio.ui.charts import DARK, current_theme

    save_settings(engine, AppSettings(language="cs", appearance="light"))
    application = Application(engine)
    try:
        first = application.window
        assert first is not None and not theme.is_dark()
        settings = first._settings
        settings._appearance.setCurrentIndex(settings._appearance.findData("dark"))
        settings._save()
        second = application.window
        assert second is not None and second is not first  # rebuilt with the new colours
        assert load_settings(engine).appearance == "dark" and theme.is_dark() and current_theme() is DARK
        assert qapp.palette().window().color().name() == theme.DARK.window
        second.close()
    finally:
        theme.apply(qapp, "light")


def test_update_can_be_stopped_and_frees_the_window(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    from taxfolio.services.sources import InputSource, SourceType, save_sources
    from taxfolio.ui import background

    started: list[object] = []
    monkeypatch.setattr(background, "start", lambda worker, name: started.append(worker))
    save_sources(window._engine, [InputSource(SourceType.FOLDER, "Složka", {"path": "/nonexistent"})])
    imp = window._import
    imp.refresh_sources()
    imp._sync_or_stop()  # start
    (worker,) = started
    assert imp._worker is worker and imp._sync_btn.text() == "Zastavit" and not imp._source.isEnabled()
    imp._sync_or_stop()  # stop
    assert worker.cancel.is_set() and imp._worker is None  # type: ignore[attr-defined]
    assert imp._sync_btn.text() == "Aktualizovat ze zdrojů" and imp._source.isEnabled()
    assert "Zastaveno" in imp._log.toPlainText()


def test_rates_download_in_background_not_in_reports(
    engine: Engine, fixtures: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from taxfolio.services import rates_service
    from taxfolio.services.settings import AppSettings, save_settings
    from taxfolio.ui import background

    import_service.import_file(engine, fixtures / "flex_2025.xml")
    save_settings(engine, AppSettings(check_updates=False))
    started: list[object] = []
    monkeypatch.setattr(background, "start", lambda worker, name: started.append(worker))
    rates_service.set_auto_download(False)
    try:
        assert rates_service.ensure_rates(engine, [2025]) == []  # reports never touch the network
        w = MainWindow(engine, background_rates=True)
        qapp.processEvents()  # the window schedules the download right after it is shown
        (worker,) = started  # only rates: the update check is off in the settings
        worker.run()  # type: ignore[attr-defined]  # what the thread does: flat test rates
        qapp.processEvents()
        assert w._rates_worker is None and "kurzy" in w._notice.message().lower()
        assert w._notice.level is not None and w._notice.level.value == "success"
        assert rates_service.missing_years(engine, [2025])["CNB"] == []
        w.close()
    finally:
        rates_service.set_auto_download(True)


def test_status_notices_show_level_and_progress(window: MainWindow, fixtures: Path) -> None:
    from taxfolio.ui.notices import Level

    notice = window._notice
    window.notify("Something went wrong", Level.ERROR)
    assert notice.isVisibleTo(window) and notice.property("level") == "error"
    assert notice.text().startswith("✕") and notice.message() == "Something went wrong"
    window.notify("Working", Level.INFO, busy=True)
    assert notice.text().startswith("⟳") and not notice._timer.isActive()  # busy stays until replaced
    window._import.import_paths([fixtures / "flex_2025.xml"])  # a manual import reports its result
    assert notice.level is Level.SUCCESS and "Import" in notice.message()
    window._import.import_paths([fixtures / "nonexistent.csv"])
    assert notice.level is Level.ERROR

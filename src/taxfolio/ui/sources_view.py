"""Settings → Data sources: list of input sources, add / edit / remove dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import Engine

from taxfolio.i18n import _
from taxfolio.services import secrets
from taxfolio.services.sources import (
    SOURCE_TYPES,
    FieldSpec,
    InputSource,
    SourceType,
    load_sources,
    remove_source,
    save_sources,
)


def source_state(source: InputSource) -> str:
    """'✔ připraveno', or what is missing."""
    try:
        missing = source.missing()
    except secrets.SecretStoreError as exc:
        return f"⚠ {exc}"
    if missing:
        return "⚠ " + _("chybí: {fields}").format(fields=", ".join(_(f.label) for f in missing))
    if source.type is SourceType.FOLDER and not Path(source.value("path")).expanduser().is_dir():
        return "⚠ " + _("složka neexistuje")
    return "✔ " + _("připraveno")


class SourceDialog(QDialog):
    """Add or edit one source; secrets go straight to the keychain on OK."""

    def __init__(self, parent: QWidget, source: InputSource | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Upravit zdroj dat") if source else _("Přidat zdroj dat"))
        self.setMinimumWidth(560)
        self._source = source
        self._inputs: dict[str, QLineEdit] = {}

        self._type = QComboBox()
        for kind, spec in SOURCE_TYPES.items():
            self._type.addItem(_(spec.title), kind.value)
        if source:
            self._type.setCurrentIndex(self._type.findData(source.type.value))
            self._type.setEnabled(False)  # fields differ per type: add a new source instead
        self._type.currentIndexChanged.connect(self._build_fields)
        self._name = QLineEdit(source.name if source else "")
        self._name.setPlaceholderText(_("např. IBKR hlavní účet"))
        self._enabled = QCheckBox(_("Zahrnout do aktualizace"))
        self._enabled.setChecked(source.enabled if source else True)
        self._description = QLabel()
        self._description.setWordWrap(True)
        self._fields_box = QWidget()
        self._fields = QFormLayout(self._fields_box)
        self._fields.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()
        form.addRow(_("Typ:"), self._type)
        form.addRow(_("Název:"), self._name)
        form.addRow("", self._enabled)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._description)
        layout.addWidget(self._fields_box)
        layout.addWidget(buttons)
        self._build_fields()

    def kind(self) -> SourceType:
        return SourceType(self._type.currentData())

    def _build_fields(self) -> None:
        while self._fields.rowCount():
            self._fields.removeRow(0)
        self._inputs.clear()
        spec = SOURCE_TYPES[self.kind()]
        self._description.setText(_(spec.description))
        default_names = {_(t.title) for t in SOURCE_TYPES.values()}
        if not self._source and self._name.text() in ("", *default_names):
            self._name.setText(_(spec.title))  # follow the type until the user names the source
        for f in spec.fields:
            edit = QLineEdit()
            edit.setPlaceholderText(_(f.placeholder) if f.placeholder else "")
            if f.secret:
                edit.setEchoMode(QLineEdit.EchoMode.Password)
                if self._source and self._stored_secret(f):
                    edit.setPlaceholderText(_("uloženo v klíčence – vyplňte jen pro změnu"))
            elif self._source:
                edit.setText(self._source.settings.get(f.key, ""))
            self._inputs[f.key] = edit
            label = _(f.label) + ("" if f.required else " " + _("(nepovinné)")) + ":"
            if f.folder:
                row = QHBoxLayout()
                row.addWidget(edit, 1)
                browse = QPushButton(_("Vybrat…"))
                browse.clicked.connect(lambda _c=False, e=edit: self._browse(e))
                row.addWidget(browse)
                self._fields.addRow(label, row)
            else:
                self._fields.addRow(label, edit)

    def _stored_secret(self, f: FieldSpec) -> bool:
        assert self._source is not None
        try:
            return bool(secrets.get_secret(self._source.id, f.key))
        except secrets.SecretStoreError:
            return False

    def _browse(self, edit: QLineEdit) -> None:
        start = str(Path(edit.text()).expanduser()) if edit.text() else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, _("Vyberte složku"), start)
        if folder:
            edit.setText(folder)

    def _accept(self) -> None:
        name = self._name.text().strip()
        if not name:
            QMessageBox.warning(self, _("Zdroj dat"), _("Zadejte název zdroje."))
            return
        spec = SOURCE_TYPES[self.kind()]
        source = self._source or InputSource(self.kind(), name)
        source.name, source.enabled = name, self._enabled.isChecked()
        source.settings = {f.key: self._inputs[f.key].text().strip() for f in spec.fields if not f.secret}
        try:
            for f in spec.fields:
                if f.secret and (value := self._inputs[f.key].text().strip()):
                    secrets.set_secret(source.id, f.key, value)
        except secrets.SecretStoreError as exc:
            QMessageBox.warning(self, _("Zdroj dat"), str(exc))
            return
        self.result_source = source
        self.accept()


class SourcesBox(QGroupBox):
    """The 'Zdroje dat' group of the settings tab. Changes are saved immediately."""

    sources_changed = Signal()

    def __init__(self, engine: Engine) -> None:
        super().__init__(_("Zdroje dat"))
        self._engine = engine
        self._sources: list[InputSource] = []

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels([_("Název"), _("Typ"), _("Stav"), _("Aktualizovat")])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().hide()
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.setMinimumHeight(130)
        self._table.doubleClicked.connect(self._edit)

        add = QPushButton(_("Přidat…"))
        add.clicked.connect(self._add)
        edit = QPushButton(_("Upravit…"))
        edit.clicked.connect(self._edit)
        remove = QPushButton(_("Odebrat"))
        remove.clicked.connect(self._remove)
        buttons = QHBoxLayout()
        for b in (add, edit, remove):
            buttons.addWidget(b)
        buttons.addStretch()

        hint = QLabel(
            _(
                "Odkud se data aktualizují tlačítkem v záložce Import. Tokeny se ukládají jen do "
                "systémové klíčenky, ne do databáze."
            )
        )
        hint.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self._table)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self) -> None:
        self._sources = load_sources(self._engine)
        self._table.setRowCount(len(self._sources))
        for row, s in enumerate(self._sources):
            values = [s.name, _(s.spec.title), source_state(s), _("ano") if s.enabled else _("ne")]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, col, item)

    def _selected(self) -> InputSource | None:
        rows = self._table.selectionModel().selectedRows()
        return self._sources[rows[0].row()] if rows else None

    def _store(self, source: InputSource) -> None:
        others = [s for s in self._sources if s.id != source.id]
        position = next((i for i, s in enumerate(self._sources) if s.id == source.id), len(others))
        save_sources(self._engine, [*others[:position], source, *others[position:]])
        self.refresh()
        self.sources_changed.emit()

    def _add(self) -> None:
        dialog = SourceDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._store(dialog.result_source)

    def _edit(self) -> None:
        source = self._selected()
        if source is None:
            return
        dialog = SourceDialog(self, source)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._store(dialog.result_source)

    def _remove(self) -> None:
        source = self._selected()
        if source is None:
            return
        answer = QMessageBox.question(
            self,
            _("Odebrat zdroj"),
            _("Odebrat zdroj „{name}“ včetně uloženého tokenu? Importovaná data zůstanou.").format(
                name=source.name
            ),
        )
        if answer == QMessageBox.StandardButton.Yes:
            try:
                remove_source(self._engine, source.id)
            except secrets.SecretStoreError as exc:
                QMessageBox.warning(self, _("Odebrat zdroj"), str(exc))
            self.refresh()
            self.sources_changed.emit()

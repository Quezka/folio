"""Tables: the datasheet and the designer."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...application.errors import ApplicationError
from ...application.inputs import ImportField, ImportSpec
from ...application.workspace import Change, Source, Workspace
from ..fit import clamp_dialog, scrollable
from ..i18n import _, plural
from .common import Card, Segmented, button, label, primary_button
from .datasheet import Datasheet
from .designer import TableDesigner, fill_type_combo, from_type_key, select_type
from .objects import Header, ObjectPage


class TablesPage(ObjectPage):
    def __init__(self, workspace: Workspace, parent=None):
        super().__init__(_("Tables"), _("Your data, in rows and columns."), _("New table"), "table",
                         _("Create a table, or import a CSV file, to start filling it."), parent)
        self.ws = workspace
        self.current: str | None = None
        self.creating = False

        card = Card(None, 14)
        self.header = Header()
        self.mode = Segmented([("data", _("Datasheet")), ("design", _("Design"))])
        self.add_row = button(_("New row"), "plus")
        self.import_csv = button(_("Import CSV…"), "download")
        self.drop = button(_("Delete table"), "trash")
        self.drop.setObjectName("danger")
        for w in (self.mode, self.add_row, self.import_csv, self.drop):
            self.header.add(w)
        self.sheet = Datasheet(workspace)
        self.designer = TableDesigner(workspace)
        self.views = QStackedWidget()
        self.views.addWidget(self.sheet)
        self.views.addWidget(self.designer)
        card.add(self.header)
        card.add(self.views, 1)
        self.add_view(card)
        self.editor_card = card

        self.items.chosen.connect(self.open_table)
        self.items.newRequested.connect(self.new_table)
        self.mode.changed.connect(self._mode)
        self.add_row.clicked.connect(self._new_row)
        self.import_csv.clicked.connect(self.import_file)
        self.drop.clicked.connect(self.delete_table)
        self.drop.setVisible(False)
        self.sheet.exportRequested.connect(self.export_file)
        self.designer.saved.connect(self._saved)
        self.designer.discarded.connect(self._discarded)
        workspace.subscribe(self._changed)
        self.refresh()

    # ---- the list --------------------------------------------------------------------
    def refresh(self, select: str | None = None):
        if not self.ws.is_open:
            self.items.set_items([])
            return
        want = select or self.current
        tables = self.ws.tables()
        self.items.set_items(
            [(t.name, f"{plural(t.row_count, 'row')} · {plural(len(t.fields), 'field')}")
             for t in tables], want, _("No tables yet."))

    def _changed(self, change):
        if change in (Change.OPENED, Change.CLOSED):
            self.current = None
            self.creating = False
            self.refresh()
        elif change is Change.SCHEMA:
            self.refresh()
        elif change is Change.DATA and self.ws.is_open and self.isVisible():
            self._update_subtitle()

    def _update_subtitle(self):
        if self.current and not self.creating:
            try:
                t = self.ws.table(self.current)
            except ApplicationError:
                return
            row = self.items.list.currentItem()
            if row is not None:
                row.setText(f"{t.name}\n{plural(t.row_count, 'row')} · {plural(len(t.fields), 'field')}")

    # ---- opening ---------------------------------------------------------------------
    def open_table(self, name: str):
        self.creating = False
        self.current = name or None
        if not name:
            self.stack.setCurrentWidget(self.placeholder)
            self.sheet.show_source(None)
            return
        record = self.ws.table(name)
        self.header.title.setText(name)
        self.stack.setCurrentWidget(self.editor_card)
        self.mode.setEnabled(True)
        self.add_row.setVisible(True)
        self.import_csv.setVisible(True)
        self.drop.setVisible(not self.ws.is_access)  # Access files keep their tables
        self.sheet.show_source(Source("table", name), editable=True)
        self.designer.load(record)
        self.mode.set_value("data")
        self.views.setCurrentWidget(self.sheet)

    def _mode(self, mode):
        if mode == "design":
            if self.current and not self.creating:
                self.designer.load(self.ws.table(self.current))
            self.views.setCurrentWidget(self.designer)
        else:
            self.views.setCurrentWidget(self.sheet)
            self.sheet.refresh()

    def new_table(self):
        self.creating = True
        self.items.list.blockSignals(True)
        self.items.list.clearSelection()
        self.items.list.setCurrentItem(None)
        self.items.list.blockSignals(False)
        self.header.title.setText(_("New table"))
        self.stack.setCurrentWidget(self.editor_card)
        self.designer.load(None)
        self.mode.setEnabled(False)
        self.mode.set_value("design")
        self.add_row.setVisible(False)
        self.import_csv.setVisible(False)
        self.drop.setVisible(False)
        self.views.setCurrentWidget(self.designer)

    def _saved(self, name: str):
        self.creating = False
        self.current = name
        self.refresh(name)
        self.open_table(name)

    def _discarded(self):
        if self.creating:
            self.creating = False
            self.refresh(self.current)
            self.open_table(self.items.current())
        elif self.current:
            self.designer.load(self.ws.table(self.current))

    def _new_row(self):
        self.mode.set_value("data")
        self._mode("data")
        self.sheet.focus_new_row()

    def delete_table(self):
        if not self.current or not self.confirm_delete(_("Delete table"), self.current):
            return
        try:
            self.ws.drop_table(self.current)
        except ApplicationError as e:
            QMessageBox.warning(self, _("Folio"), _(str(e)))
            return
        self.current = None
        self.refresh()

    # ---- CSV -------------------------------------------------------------------------
    def _folder(self) -> str:
        folder = QSettings().value("folder", "")
        return folder if folder and Path(folder).is_dir() else str(Path.home())

    def import_file(self, path: str | None = None):
        path = path or QFileDialog.getOpenFileName(
            self, _("Import CSV"), self._folder(),
            _("Tables") + " (*.csv *.tsv *.txt);;" + _("All files") + " (*)")[0]
        if not path:
            return
        QSettings().setValue("folder", str(Path(path).parent))
        try:
            dialog = ImportDialog(self.ws, path, self.current, self)
        except ApplicationError as e:
            QMessageBox.warning(self, _("Import CSV"), _(str(e)))
            return
        if dialog.exec() == QDialog.Accepted and dialog.result_name:
            self.refresh(dialog.result_name)
            self.open_table(dialog.result_name)

    def export_file(self):
        if not self.current:
            return
        path = QFileDialog.getSaveFileName(
            self, _("Export as CSV"), str(Path(self._folder()) / f"{self.current}.csv"),
            _("CSV files") + " (*.csv)")[0]
        if not path:
            return
        try:
            n = self.ws.export_csv(Source("table", self.current), path)
        except ApplicationError as e:
            QMessageBox.warning(self, _("Export as CSV"), _(str(e)))
            return
        QMessageBox.information(self, _("Export as CSV"),
                                _("Saved {rows}.").format(rows=plural(n, "row")))


class ImportDialog(QDialog):
    """Pick the table name and the types of the columns of a CSV file."""

    def __init__(self, workspace: Workspace, path: str, append_to: str | None, parent=None):
        super().__init__(parent)
        self.ws = workspace
        self.path = path
        self.result_name = ""
        self.setWindowTitle(_("Import CSV"))
        self.preview = workspace.preview_csv(path, True)

        self.name = QLineEdit(Path(path).stem)
        self.append = QComboBox()
        self.append.addItem(_("A new table"), None)
        for t in workspace.table_names():
            self.append.addItem(_("Add to “{table}”").format(table=t), t)
        if append_to:
            self.append.setCurrentIndex(max(0, self.append.findData(append_to)))
        self.header = QCheckBox(_("The first row has the column names"))
        self.header.setChecked(True)
        self.key = QCheckBox(_("Add an “id” field that counts up by itself"))
        self.key.setChecked(True)
        self.grid = QTableWidget()
        self.message = QLabel(objectName="danger")
        self.message.setWordWrap(True)
        self.message.hide()
        ok = primary_button(_("Import"), "download")
        cancel = button(_("Cancel"))
        ok.clicked.connect(self._import)
        cancel.clicked.connect(self.reject)
        self.header.toggled.connect(self._reload)
        self.append.currentIndexChanged.connect(self._mode)

        form = QFormLayout()
        form.addRow(_("Into"), self.append)
        form.addRow(_("Table name"), self.name)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(ok)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(label(_("{rows} found in {file}.").format(
            rows=plural(self.preview.total_rows, "row"), file=Path(path).name), "muted"))
        layout.addLayout(form)
        layout.addWidget(self.header)
        layout.addWidget(self.key)
        layout.addWidget(self.grid, 1)
        layout.addWidget(self.message)
        layout.addLayout(row)
        self._fill()
        self._mode()
        scrollable(self)
        clamp_dialog(self, 760, 560)

    def _reload(self):
        self.preview = self.ws.preview_csv(self.path, self.header.isChecked())
        self._fill()

    def _fill(self):
        p = self.preview
        self.grid.clear()
        self.grid.setColumnCount(len(p.header))
        self.grid.setRowCount(len(p.rows) + 3)
        self.grid.setVerticalHeaderLabels([_("Keep"), _("Field"), _("Type")] +
                                          [str(i + 1) for i in range(len(p.rows))])
        self.grid.setHorizontalHeaderLabels([f"#{i + 1}" for i in range(len(p.header))])
        for c, (name, ftype) in enumerate(zip(p.header, p.types)):
            keep = QCheckBox()
            keep.setChecked(True)
            self.grid.setCellWidget(0, c, keep)
            self.grid.setItem(1, c, QTableWidgetItem(name))
            box = QComboBox()
            fill_type_combo(box)
            select_type(box, ftype, p.currencies[c])
            self.grid.setCellWidget(2, c, box)
            for r, row in enumerate(p.rows):
                item = QTableWidgetItem(row[c])
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.grid.setItem(r + 3, c, item)
        self.grid.resizeColumnsToContents()

    def _mode(self):
        appending = self.append.currentData() is not None
        self.name.setEnabled(not appending)
        self.key.setEnabled(not appending)
        if appending:
            self.name.setText(self.append.currentData())

    def _import(self):
        fields = []
        for c in range(self.grid.columnCount()):
            if self.grid.cellWidget(0, c).isChecked():
                ftype, currency = from_type_key(self.grid.cellWidget(2, c).currentData())
                fields.append(ImportField(self.grid.item(1, c).text().strip() or f"Column {c + 1}",
                                          ftype, c, currency))
        spec = ImportSpec(self.path, self.name.text().strip(), tuple(fields),
                          self.header.isChecked(), self.key.isChecked() and self.key.isEnabled(),
                          self.append.currentData() is not None)
        try:
            result = self.ws.import_csv(spec)
        except ApplicationError as e:
            self.message.setText(_(str(e)))
            self.message.show()
            return
        self.result_name = result.table
        if result.problems:
            QMessageBox.information(self, _("Import CSV"), _(
                "{rows} imported. {problems} didn't fit their type and were left empty.").format(
                rows=plural(result.rows, "row"), problems=result.problems))
        self.accept()

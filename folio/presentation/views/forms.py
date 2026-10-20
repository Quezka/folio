"""Forms: one record at a time, laid out the way you choose."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QScrollArea, QStackedWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget, QFrame,
)

from ...application.errors import ApplicationError, IncompleteRowError
from ...application.inputs import FormDef, FormField
from ...application.types import FieldType, RowQuery
from ...application.workspace import Change, Source, Workspace
from ..fit import clamp_dialog
from ..i18n import _
from .common import Card, Segmented, button, caption, icon_button, label, primary_button
from .datasheet import edit_text, format_value
from .objects import Header, ObjectPage


def pick_source(ws: Workspace, parent, title: str, with_name: bool = True):
    """Ask for a name and a table or query. Returns (name, Source) or None."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    name = QLineEdit()
    source = QComboBox()
    for t in ws.table_names():
        source.addItem(_("Table: {name}").format(name=t), Source("table", t))
    for q in ws.queries():
        source.addItem(_("Query: {name}").format(name=q), Source("query", q))
    ok, cancel = primary_button(_("Create"), "plus"), button(_("Cancel"))
    ok.clicked.connect(dialog.accept)
    cancel.clicked.connect(dialog.reject)
    form = QFormLayout()
    form.addRow(_("Based on"), source)
    if with_name:
        form.addRow(_("Name"), name)
    row = QHBoxLayout()
    row.addStretch()
    row.addWidget(cancel)
    row.addWidget(ok)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(20, 20, 20, 16)
    layout.addLayout(form)
    layout.addLayout(row)
    dialog.setMinimumWidth(380)
    if source.count() == 0:
        QMessageBox.information(parent, title, _("Create a table first."))
        return None
    if dialog.exec() != QDialog.Accepted:
        return None
    chosen = source.currentData()
    return (name.text().strip() or chosen.name), chosen


class FormView(QWidget):
    """Shows and edits one record of the form's source."""

    def __init__(self, workspace: Workspace, parent=None):
        super().__init__(parent)
        self.ws = workspace
        self.form: FormDef | None = None
        self.index = 0
        self.total = 0
        self.adding = False
        self.editors: dict[str, QWidget] = {}
        self.columns = []
        self.options: dict[str, list] = {}
        self._loading = False

        self.first = icon_button("chevron-left", _("Previous record"))
        self.next = icon_button("chevron-right", _("Next record"))
        self.position = QLabel(objectName="muted")
        self.search = QLineEdit(objectName="search", placeholderText=_("Search…"))
        self.search.setMaximumWidth(220)
        self.search.setClearButtonEnabled(True)
        self.add = button(_("New record"), "plus")
        self.save = primary_button(_("Add record"), "check")
        self.cancel = button(_("Cancel"))
        self.delete = icon_button("trash", _("Delete this record"))
        self.message = QLabel(objectName="danger")
        self.message.setWordWrap(True)
        self.message.hide()
        self.first.clicked.connect(lambda: self.go(self.index - 1))
        self.next.clicked.connect(lambda: self.go(self.index + 1))
        self.search.textChanged.connect(lambda _t: self.go(0))
        self.add.clicked.connect(self.start_adding)
        self.save.clicked.connect(self.commit_new)
        self.cancel.clicked.connect(self.stop_adding)
        self.delete.clicked.connect(self.delete_record)

        nav = QHBoxLayout()
        nav.setSpacing(6)
        for w in (self.first, self.position, self.next, self.search):
            nav.addWidget(w)
        nav.addStretch()
        for w in (self.cancel, self.save, self.add, self.delete):
            nav.addWidget(w)
        self.body = QWidget()
        self.grid = QGridLayout(self.body)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        h = QVBoxLayout(holder)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.body)
        h.addStretch()
        scroll.setWidget(holder)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(nav)
        layout.addWidget(self.message)
        layout.addWidget(scroll, 1)

    # ---- building --------------------------------------------------------------------
    def load(self, form: FormDef):
        self.form = form
        self.adding = False
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.source = Source(form.source_kind, form.source)
        self.editable = form.source_kind == "table"
        try:
            self.columns = {c.name: c for c in self.ws.columns(self.source)}
        except ApplicationError as e:
            self.columns = {}
            self.message.setText(_(str(e)))
            self.message.show()
        self._build()
        self.go(0)

    def _build(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.editors = {}
        self.options = {}
        per_column = max(1, self.form.columns)
        for n, f in enumerate(self.form.fields):
            col = self.columns.get(f.name)
            if col is None:
                continue
            editor = self._editor_for(f, col)
            cell = QWidget()
            v = QVBoxLayout(cell)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(3)
            text = (f.label or f.name) + (" *" if col.required else "")
            v.addWidget(caption(text))
            v.addWidget(editor)
            self.grid.addWidget(cell, n // per_column, n % per_column)
            self.editors[f.name] = editor
        for c in range(per_column):
            self.grid.setColumnStretch(c, 1)

    def _editor_for(self, f: FormField, col):
        read_only = f.read_only or not self.editable or not col.editable
        if col.ref_table:
            box = QComboBox()
            table = self.ws.table(self.source.name).field(col.name)
            box.addItem("", None)
            opts = self.ws.lookup(col.ref_table, table.ref_field)
            for o in opts:
                box.addItem(o.label or str(o.key), o.key)
            box.setEnabled(not read_only)
            box.activated.connect(lambda _i, n=f.name: self._commit_field(n))
            return box
        if col.type is FieldType.YES_NO:
            box = QCheckBox(_("Yes"))
            box.setEnabled(not read_only)
            box.clicked.connect(lambda _c, n=f.name: self._commit_field(n))
            return box
        if col.type is FieldType.LONG_TEXT:
            edit = QPlainTextEdit()
            edit.setFixedHeight(110)
            edit.setReadOnly(read_only)
            edit.focusOutEvent = self._wrap_focus_out(edit, f.name)
            return edit
        edit = QLineEdit()
        edit.setReadOnly(read_only)
        if col.type in (FieldType.DATE, FieldType.DATETIME):
            edit.setPlaceholderText("2026-10-20")
        edit.editingFinished.connect(lambda n=f.name: self._commit_field(n))
        return edit

    def _wrap_focus_out(self, edit, name):
        original = edit.focusOutEvent

        def handler(event):
            original(event)
            self._commit_field(name)
        return handler

    def _text_of(self, editor) -> str:
        if isinstance(editor, QComboBox):
            return "" if editor.currentData() is None else str(editor.currentData())
        if isinstance(editor, QCheckBox):
            return "yes" if editor.isChecked() else "no"
        if isinstance(editor, QPlainTextEdit):
            return editor.toPlainText()
        return editor.text()

    def _set_editor(self, editor, value, col):
        self._loading = True
        if isinstance(editor, QComboBox):
            editor.setCurrentIndex(max(0, editor.findData(value)))
        elif isinstance(editor, QCheckBox):
            editor.setChecked(bool(value))
        elif isinstance(editor, QPlainTextEdit):
            editor.setPlainText(edit_text(value, col.type))
        else:
            editor.setText(edit_text(value, col.type) if self.editable else format_value(value, col.type))
        self._loading = False

    # ---- navigating ------------------------------------------------------------------
    def _query(self) -> RowQuery:
        return RowQuery(self.search.text())

    def go(self, index: int):
        if self.form is None or self.adding:
            return
        self.message.hide()
        try:
            total = self.ws.page(self.source, self._query(), 0, 1).total
        except ApplicationError as e:
            self.message.setText(_(str(e)))
            self.message.show()
            return
        self.total = total
        self.index = max(0, min(index, total - 1)) if total else 0
        self.row_key = None
        values = None
        if total:
            page = self.ws.page(self.source, self._query(), self.index, 1)
            if page.rows:
                self.row_key = page.rows[0].key
                values = page.rows[0].values
        names = [c for c in self.columns]
        for name, editor in self.editors.items():
            col = self.columns[name]
            value = values[names.index(name)] if values is not None else None
            self._set_editor(editor, value, col)
            editor.setEnabled(values is not None)
        self._update_nav()

    def _can_edit(self, name: str) -> bool:
        f = next((f for f in self.form.fields if f.name == name), None)
        col = self.columns.get(name)
        return bool(f and col and self.editable and col.editable and not f.read_only)

    def _update_nav(self):
        self.first.setEnabled(not self.adding and self.index > 0)
        self.next.setEnabled(not self.adding and self.index < self.total - 1)
        self.search.setEnabled(not self.adding)
        self.position.setText(_("New record") if self.adding else (
            _("{n} of {total}").format(n=self.index + 1, total=self.total) if self.total
            else _("No records")))
        self.add.setVisible(self.editable and not self.adding)
        self.delete.setVisible(self.editable and not self.adding)
        self.delete.setEnabled(self.total > 0)
        self.save.setVisible(self.adding)
        self.cancel.setVisible(self.adding)

    def refresh(self):
        if self.form is not None and not self.adding:
            self.go(self.index)

    # ---- editing ---------------------------------------------------------------------
    def _commit_field(self, name: str):
        if self._loading or self.adding or not self.editable or self.row_key is None:
            return
        try:
            self.ws.update_cell(self.source.name, self.row_key, name, self._text_of(self.editors[name]))
            self.message.hide()
        except ApplicationError as e:
            self.message.setText(_(str(e)))
            self.message.show()
            self.go(self.index)

    def start_adding(self):
        self.adding = True
        self.message.hide()
        for name, editor in self.editors.items():
            col = self.columns[name]
            self._set_editor(editor, None, col)
            editor.setEnabled(self._can_edit(name))
        self._update_nav()
        first = next((e for n, e in self.editors.items() if self._can_edit(n)), None)
        if first is not None:
            first.setFocus()

    def stop_adding(self):
        self.adding = False
        self.go(self.index)

    def commit_new(self):
        texts = {n: self._text_of(e) for n, e in self.editors.items() if self._can_edit(n)}
        texts = {n: t for n, t in texts.items() if t != "" and not (
            isinstance(self.editors[n], QCheckBox) and t == "no")}
        try:
            self.ws.insert_row(self.source.name, texts)
        except IncompleteRowError as e:
            self.message.setText(_(str(e)))
            self.message.show()
            return
        except ApplicationError as e:
            self.message.setText(_(str(e)))
            self.message.show()
            return
        self.adding = False
        self.search.clear()
        self.go(10 ** 9)  # the new row is the last

    def delete_record(self):
        if self.row_key is None:
            return
        if QMessageBox.question(self, _("Delete record"),
                                _("Delete this record? You can undo it from the Tables page.")) != QMessageBox.Yes:
            return
        try:
            self.ws.delete_rows(self.source.name, [self.row_key])
        except ApplicationError as e:
            self.message.setText(_(str(e)))
            self.message.show()
            return
        self.go(self.index)


class FormDesigner(QWidget):
    """Which fields, in what order, under what label, in how many columns."""

    changed = None

    def __init__(self, workspace: Workspace, parent=None):
        super().__init__(parent)
        self.ws = workspace
        self.form: FormDef | None = None
        self.title = QLineEdit(objectName="titleEdit", placeholderText=_("Form title"))
        self.columns = Segmented([(1, _("1 column")), (2, _("2 columns")), (3, _("3 columns"))])
        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setHeaderLabels([_("Show"), _("Field"), _("Label")])
        self.tree.setColumnWidth(0, 70)
        self.tree.setColumnWidth(1, 200)
        self.up = icon_button("chevron-up", _("Move up"))
        self.down = icon_button("chevron-down", _("Move down"))
        self.up.clicked.connect(lambda: self._move(-1))
        self.down.clicked.connect(lambda: self._move(1))
        row = QHBoxLayout()
        row.addWidget(self.columns)
        row.addStretch()
        row.addWidget(self.up)
        row.addWidget(self.down)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.title)
        layout.addLayout(row)
        layout.addWidget(self.tree, 1)
        layout.addWidget(label(_("Double-click a label to rename it."), "hint"))

    def load(self, form: FormDef):
        self.form = form
        self.title.setText(form.title)
        self.columns.set_value(form.columns)
        self.tree.clear()
        known = {c.name for c in self.ws.columns(Source(form.source_kind, form.source))}
        shown = [f for f in form.fields if f.name in known]
        rest = [FormField(n, n) for n in sorted(known - {f.name for f in shown},
                                                 key=lambda n: list(known).index(n))]
        for f, on in [(f, True) for f in shown] + [(f, False) for f in rest]:
            item = QTreeWidgetItem(["", f.name, f.label or f.name])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
            item.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
            item.setData(1, Qt.UserRole, f.read_only)
            self.tree.addTopLevelItem(item)

    def _move(self, step: int):
        item = self.tree.currentItem()
        if item is None:
            return
        i = self.tree.indexOfTopLevelItem(item)
        j = i + step
        if not 0 <= j < self.tree.topLevelItemCount():
            return
        self.tree.takeTopLevelItem(i)
        self.tree.insertTopLevelItem(j, item)
        self.tree.setCurrentItem(item)

    def result(self) -> FormDef:
        fields = []
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.checkState(0) == Qt.Checked:
                fields.append(FormField(it.text(1), it.text(2).strip() or it.text(1),
                                        bool(it.data(1, Qt.UserRole))))
        f = self.form
        return FormDef(f.source, f.source_kind, self.title.text().strip(), tuple(fields),
                       self.columns.value() or 1)


class FormsPage(ObjectPage):
    def __init__(self, workspace: Workspace, parent=None):
        super().__init__(_("Forms"), _("Look at and edit one record at a time."), _("New form"),
                         "form", _("Create a form from a table or a query."), parent)
        self.ws = workspace
        self.current: str | None = None
        self.view = FormView(workspace)
        self.designer = FormDesigner(workspace)
        card = Card(None, 14)
        self.header = Header()
        self.mode = Segmented([("form", _("Form")), ("design", _("Design"))])
        self.save_button = primary_button(_("Save design"), "check")
        self.delete_button = button(_("Delete"), "trash")
        self.delete_button.setObjectName("danger")
        for w in (self.mode, self.save_button, self.delete_button):
            self.header.add(w)
        self.views = QStackedWidget()
        self.views.addWidget(self.view)
        self.views.addWidget(self.designer)
        card.add(self.header)
        card.add(self.views, 1)
        self.add_view(card)
        self.card = card
        self.items.chosen.connect(self.open_form)
        self.items.newRequested.connect(self.new_form)
        self.mode.changed.connect(self._mode)
        self.save_button.clicked.connect(self.save_design)
        self.delete_button.clicked.connect(self.delete)
        workspace.subscribe(self._changed)
        self.refresh()

    def refresh(self, select: str | None = None):
        if not self.ws.is_open:
            self.items.set_items([])
            return
        want = select or self.current
        self.items.set_items([(n, self.ws.form(n).source) for n in self.ws.forms()], want,
                             _("No forms yet."))

    def _changed(self, change):
        if change in (Change.OPENED, Change.CLOSED):
            self.current = None
            self.refresh()
        elif change is Change.DATA and self.isVisible() and self.current:
            self.view.refresh()
        elif change is Change.SCHEMA and self.ws.is_open:
            self.refresh()

    def open_form(self, name: str):
        self.current = name or None
        if not name:
            self.stack.setCurrentWidget(self.placeholder)
            return
        form = self.ws.form(name)
        self.header.title.setText(name)
        self.stack.setCurrentWidget(self.card)
        self.view.load(form)
        self.designer.load(form)
        self.mode.set_value("form")
        self.views.setCurrentWidget(self.view)
        self.save_button.setVisible(False)

    def _mode(self, mode):
        design = mode == "design"
        self.save_button.setVisible(design)
        if design:
            self.designer.load(self.ws.form(self.current))
        else:
            self.view.load(self.ws.form(self.current))
        self.views.setCurrentWidget(self.designer if design else self.view)

    def new_form(self):
        picked = pick_source(self.ws, self, _("New form"))
        if not picked:
            return
        name, source = picked
        n, base = name, 2
        while n in self.ws.forms():
            n, base = f"{name} {base}", base + 1
        try:
            self.ws.save_form(n, None, self.ws.default_form(source))
        except ApplicationError as e:
            QMessageBox.warning(self, _("Folio"), _(str(e)))
            return
        self.refresh(n)
        self.open_form(n)

    def save_design(self):
        try:
            self.ws.save_form(self.current, self.current, self.designer.result())
        except ApplicationError as e:
            QMessageBox.warning(self, _("Folio"), _(str(e)))
            return
        self.mode.set_value("form")
        self._mode("form")
        self.save_button.setVisible(False)

    def delete(self):
        if self.current and self.confirm_delete(_("Delete form"), self.current):
            self.ws.delete_form(self.current)
            self.current = None
            self.refresh()

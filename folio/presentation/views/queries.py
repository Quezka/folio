"""Queries: tick fields, type criteria, see the rows and the SQL."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ...application.errors import ApplicationError
from ...application.inputs import Join, QueryColumn, QueryDesign
from ...application.types import JOIN_KINDS, SORTS, TOTALS
from ...application.workspace import Change, Source, Workspace
from ..i18n import N_, _, Translated
from .common import Card, Segmented, button, caption, label, primary_button
from .datasheet import Datasheet
from .objects import Header, ObjectPage

SORT_NAMES = Translated({"": N_("(none)"), "asc": N_("Ascending"), "desc": N_("Descending")})
TOTAL_NAMES = Translated({"": N_("(plain)"), "group": N_("Group by"), "sum": N_("Sum"),
                          "avg": N_("Average"), "min": N_("Smallest"), "max": N_("Largest"),
                          "count": N_("Count")})
FIELD, SHOW, SORT, TOTAL, CRITERIA, OR = range(6)


class QueryEditor(QWidget):
    """Design grid + SQL, with the result underneath."""

    def __init__(self, workspace: Workspace, parent=None):
        super().__init__(parent)
        self.ws = workspace
        self.tables: list[str] = []
        self.joins: tuple[Join, ...] = ()
        self.raw = False  # the SQL was written by hand
        self._loading = False

        self.add_table = QComboBox()
        self.add_table.setMinimumWidth(150)
        self.add_table.activated.connect(self._add_table_chosen)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        self.distinct = QCheckBox(_("Only different rows"))
        self.distinct.toggled.connect(self._changed)
        self.fields = QTreeWidget()
        self.fields.setHeaderHidden(True)
        self.fields.setObjectName("compact")
        self.fields.setMaximumWidth(170)
        self.fields.itemDoubleClicked.connect(self._field_double_clicked)
        self.fields.setToolTip(_("Double-click a field to add it to the query"))
        self.joins_label = label("", "hint")
        self.joins_label.setWordWrap(True)
        self.grid = QTableWidget(0, 6)
        self.grid.setHorizontalHeaderLabels([_("Field"), _("Show"), _("Sort"), _("Total"),
                                             _("Criteria"), _("or")])
        self.grid.verticalHeader().setVisible(False)
        self.grid.verticalHeader().setDefaultSectionSize(34)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.grid.setSelectionMode(QAbstractItemView.SingleSelection)
        h = self.grid.horizontalHeader()
        for col, width in ((FIELD, 160), (SHOW, 54), (SORT, 104), (TOTAL, 98)):
            h.setSectionResizeMode(col, QHeaderView.Fixed)
            self.grid.setColumnWidth(col, width)
        h.setSectionResizeMode(CRITERIA, QHeaderView.Stretch)
        h.setSectionResizeMode(OR, QHeaderView.Stretch)
        self.grid.itemChanged.connect(lambda _i: self._changed())
        self.remove_field = button(_("Remove field"), "trash")
        self.remove_field.clicked.connect(self._remove_field)
        self.hint = label(_("Criteria: 5, >10, between 1 and 9, like \"A*\", is null, "
                            "\"Rome\" or \"Milan\""), "hint")

        design_top = QHBoxLayout()
        design_top.addWidget(caption(_("Tables")))
        design_top.addWidget(self.add_table)
        design_top.addLayout(self.chips)
        design_top.addStretch()
        design_top.addWidget(self.distinct)
        right = QVBoxLayout()
        right.addWidget(self.grid, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(self.remove_field)
        bottom.addWidget(self.hint, 1)
        right.addLayout(bottom)
        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(self.fields, 1)
        left.addWidget(self.joins_label)
        body.addLayout(left)
        body.addLayout(right, 1)
        self.design = QWidget()
        d = QVBoxLayout(self.design)
        d.setContentsMargins(0, 0, 0, 0)
        d.addLayout(design_top)
        d.addLayout(body, 1)

        self.sql = QPlainTextEdit(objectName="code")
        self.sql.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.sql.setPlaceholderText(_("SELECT … FROM …"))
        self.sql.textChanged.connect(self._sql_edited)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.design)
        self.stack.addWidget(self.sql)
        self.mode = Segmented([("design", _("Design")), ("sql", _("SQL"))])
        self.mode.set_value("design")
        self.mode.changed.connect(self._mode_changed)

        self.error = QLabel(objectName="danger")
        self.error.setWordWrap(True)
        self.error.hide()
        self.result = Datasheet(workspace)
        self.result.export_button.hide()
        self.timer = QTimer(self, singleShot=True, interval=350)
        self.timer.timeout.connect(self.run)

        top = QWidget()
        t = QVBoxLayout(top)
        t.setContentsMargins(0, 0, 0, 0)
        t.addWidget(self.stack)
        bottom_w = QWidget()
        b = QVBoxLayout(bottom_w)
        b.setContentsMargins(0, 0, 0, 0)
        b.addWidget(self.error)
        b.addWidget(self.result, 1)
        self.split = QSplitter(Qt.Vertical)
        self.split.addWidget(top)
        self.split.addWidget(bottom_w)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 2)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.split, 1)
        workspace.subscribe(self._workspace_changed)

    # ---- state -----------------------------------------------------------------------
    def load(self, design: QueryDesign | None, sql: str):
        self._loading = True
        self.raw = design is None and bool(sql)
        self.tables = list(design.tables) if design else []
        self.joins = tuple(design.joins) if design else ()
        self.distinct.setChecked(bool(design and design.distinct))
        self.grid.setRowCount(0)
        self._refresh_pickers()
        for c in (design.columns if design else ()):
            self._add_row(c)
        self.sql.setPlainText(sql)
        self.mode.set_value("sql" if self.raw else "design")
        self.stack.setCurrentIndex(1 if self.raw else 0)
        self.mode.group.button(0).setEnabled(True)
        self._loading = False
        self.run()

    def clear(self):
        self.load(None, "")

    def current_design(self) -> QueryDesign | None:
        if self.raw:
            return None
        columns = []
        for row in range(self.grid.rowCount()):
            field = self.grid.cellWidget(row, FIELD).currentData()
            if field is None:
                continue
            table, name = field.split("\t")
            columns.append(QueryColumn(
                table, name, self.grid.cellWidget(row, SHOW).check.isChecked(),
                self.grid.cellWidget(row, SORT).currentData(),
                self.grid.cellWidget(row, TOTAL).currentData(),
                self._text(row, CRITERIA), self._text(row, OR)))
        return QueryDesign(tuple(self.tables), self.joins, tuple(columns), self.distinct.isChecked())

    def current_sql(self) -> str:
        if self.raw:
            return self.sql.toPlainText().strip()
        return self.generated_sql()

    def generated_sql(self) -> str:
        design = self.current_design()
        if design is None or not design.columns:
            return ""
        try:
            return self.ws.build_sql(design)
        except ApplicationError:
            return ""

    def _text(self, row: int, col: int) -> str:
        item = self.grid.item(row, col)
        return item.text().strip() if item else ""

    # ---- tables and fields -------------------------------------------------------------
    def _refresh_pickers(self):
        names = self.ws.table_names()
        self.tables = [t for t in self.tables if t in names]
        self.add_table.blockSignals(True)
        self.add_table.clear()
        self.add_table.addItem(_("Add table…"), None)
        for n in names:
            if n not in self.tables:
                self.add_table.addItem(n, n)
        self.add_table.blockSignals(False)
        while self.chips.count():
            item = self.chips.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for n in self.tables:
            chip = QToolButton(objectName="tool", text=f"{n}  ✕")
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _c=False, n=n: self._remove_table(n))
            self.chips.addWidget(chip)
        self.fields.clear()
        for t in self.ws.tables():
            if t.name in self.tables:
                parent = QTreeWidgetItem([t.name])
                parent.setFirstColumnSpanned(True)
                self.fields.addTopLevelItem(parent)
                star = QTreeWidgetItem(parent, ["*"])
                star.setData(0, Qt.UserRole, (t.name, "*"))
                for f in t.fields:
                    item = QTreeWidgetItem(parent, [f.name])
                    item.setData(0, Qt.UserRole, (t.name, f.name))
                parent.setExpanded(True)
        if self.joins:
            self.joins_label.setText(_("Joined by relationships:") + "\n" + "\n".join(
                f"{j.left_table}.{j.left_field} = {j.right_table}.{j.right_field}"
                + (" (" + _("keep all of the first") + ")" if j.kind == "left" else "")
                for j in self.joins))
        else:
            self.joins_label.setText("")

    def _add_table_chosen(self, _i):
        name = self.add_table.currentData()
        if not name:
            return
        self.tables.append(name)
        self.joins = self.ws.suggest_joins(self.tables, self.joins)
        self._refresh_pickers()
        self._changed()

    def _remove_table(self, name: str):
        self.tables.remove(name)
        self.joins = tuple(j for j in self.joins
                           if name not in (j.left_table, j.right_table))
        for row in reversed(range(self.grid.rowCount())):
            field = self.grid.cellWidget(row, FIELD).currentData()
            if field and field.split("\t")[0] == name:
                self.grid.removeRow(row)
        self._refresh_pickers()
        self._refill_field_boxes()
        self._changed()

    def _field_choices(self) -> list[tuple[str, tuple]]:
        choices = []
        for t in self.ws.tables():
            if t.name in self.tables:
                choices += [(f"{t.name}.{f.name}", f"{t.name}\t{f.name}") for f in t.fields]
        return choices

    def _refill_field_boxes(self):
        pass  # boxes are rebuilt only when a table is removed; rows of removed tables are gone

    def _field_double_clicked(self, item, _col):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        table, field = data
        if field == "*":
            for t in self.ws.tables():
                if t.name == table:
                    for f in t.fields:
                        self._add_row(QueryColumn(table, f.name))
        else:
            self._add_row(QueryColumn(table, field))
        self._changed()

    def _add_row(self, c: QueryColumn):
        row = self.grid.rowCount()
        self.grid.insertRow(row)
        box = QComboBox()
        for text, data in self._field_choices():
            box.addItem(text, data)
        box.setCurrentIndex(max(0, box.findData(f"{c.table}\t{c.field}")))
        box.currentIndexChanged.connect(lambda _i: self._changed())
        self.grid.setCellWidget(row, FIELD, box)
        show = QCheckBox()
        show.setChecked(c.show)
        show.toggled.connect(lambda _c: self._changed())
        holder = QWidget()
        h = QHBoxLayout(holder)
        h.setContentsMargins(0, 0, 0, 0)
        h.setAlignment(Qt.AlignCenter)
        h.addWidget(show)
        holder.check = show
        self.grid.setCellWidget(row, SHOW, holder)
        for col, names, value in ((SORT, SORT_NAMES, c.sort), (TOTAL, TOTAL_NAMES, c.total)):
            combo = QComboBox()
            for key in (SORTS if col == SORT else TOTALS):
                combo.addItem(names[key], key)
            combo.setCurrentIndex(max(0, combo.findData(value)))
            combo.currentIndexChanged.connect(lambda _i: self._changed())
            self.grid.setCellWidget(row, col, combo)
        self.grid.setItem(row, CRITERIA, QTableWidgetItem(c.criteria))
        self.grid.setItem(row, OR, QTableWidgetItem(c.or_criteria))

    def _remove_field(self):
        row = self.grid.currentRow()
        if row >= 0:
            self.grid.removeRow(row)
            self._changed()

    # ---- running ---------------------------------------------------------------------
    def _changed(self):
        if self._loading:
            return
        if not self.raw:
            self.sql.blockSignals(True)
            self.sql.setPlainText(self.generated_sql())
            self.sql.blockSignals(False)
        self.timer.start()

    def _sql_edited(self):
        if self._loading:
            return
        if self.stack.currentIndex() == 1 and not self.raw:
            self.raw = True
        self.timer.start()

    def _mode_changed(self, mode):
        if mode == "design" and self.raw:
            answer = QMessageBox.question(
                self, _("Design view"),
                _("This query was written as SQL. Going back to the design discards your SQL "
                  "and uses the design instead. Continue?"))
            if answer != QMessageBox.Yes:
                self.mode.set_value("sql")
                return
            self.raw = False
            self._changed()
        self.stack.setCurrentIndex(0 if mode == "design" else 1)

    def run(self):
        sql = self.current_sql()
        if not sql:
            self.error.hide()
            self.result.show_source(None)
            return
        try:
            self.ws.check_sql(sql)
            self.result.show_source(Source("sql", sql), editable=False)
            self.error.hide()
        except ApplicationError as e:
            self.error.setText(_(str(e)))
            self.error.show()
            self.result.show_source(None)

    def _workspace_changed(self, change):
        if change is Change.SCHEMA and self.ws.is_open and self.isVisible():
            self._refresh_pickers()


class QueriesPage(ObjectPage):
    def __init__(self, workspace: Workspace, parent=None):
        super().__init__(_("Queries"), _("Ask your data a question."), _("New query"), "query",
                         _("Create a query: pick tables, tick fields, add criteria."), parent)
        self.ws = workspace
        self.current: str | None = None
        self.editor = QueryEditor(workspace)
        card = Card(None, 14)
        self.header = Header()
        self.name = QLineEdit(placeholderText=_("Query name"))
        self.name.setMinimumWidth(200)
        self.save_button = primary_button(_("Save"), "check")
        self.delete_button = button(_("Delete"), "trash")
        self.delete_button.setObjectName("danger")
        self.header.title.hide()
        self.header.row.insertWidget(0, self.name)
        for w in (self.editor.mode, self.save_button, self.delete_button):
            self.header.add(w)
        card.add(self.header)
        card.add(self.editor, 1)
        self.add_view(card)
        self.card = card
        self.items.chosen.connect(self.open_query)
        self.items.newRequested.connect(self.new_query)
        self.save_button.clicked.connect(self.save)
        self.delete_button.clicked.connect(self.delete)
        workspace.subscribe(self._changed)
        self.refresh()

    def refresh(self, select: str | None = None):
        if not self.ws.is_open:
            self.items.set_items([])
            return
        names = self.ws.queries()
        want = select if select is not None else self.current
        self.items.set_items([(n, _("SQL") if self.ws.query(n).design is None else _("Designed"))
                              for n in names], want, _("No queries yet."))

    def _changed(self, change):
        if change in (Change.OPENED, Change.CLOSED):
            self.current = None
            self.refresh()
        elif change is Change.OBJECTS and self.isVisible():
            pass

    def open_query(self, name: str):
        self.current = name or None
        if not name:
            if self.stack.currentWidget() is self.card and self.name.text() and not self._creating:
                self.stack.setCurrentWidget(self.placeholder)
            elif not getattr(self, "_creating", False):
                self.stack.setCurrentWidget(self.placeholder)
            return
        self._creating = False
        record = self.ws.query(name)
        self.name.setText(name)
        self.stack.setCurrentWidget(self.card)
        self.delete_button.setVisible(True)
        self.editor.load(record.design, record.sql)

    _creating = False

    def new_query(self):
        self._creating = True
        self.current = None
        self.items.list.blockSignals(True)
        self.items.list.setCurrentItem(None)
        self.items.list.blockSignals(False)
        self.name.setText("")
        self.stack.setCurrentWidget(self.card)
        self.delete_button.setVisible(False)
        self.editor.clear()
        self.name.setFocus()

    def save(self):
        sql = self.editor.current_sql()
        try:
            if not sql:
                raise ApplicationError("Add at least one field to the query.")
            self.ws.save_query(self.name.text(), self.current, sql, self.editor.current_design())
        except ApplicationError as e:
            QMessageBox.warning(self, _("Folio"), _(str(e)))
            return
        self._creating = False
        self.current = self.name.text().strip()
        self.refresh(self.current)
        self.delete_button.setVisible(True)

    def delete(self):
        if self.current and self.confirm_delete(_("Delete query"), self.current):
            self.ws.delete_query(self.current)
            self.current = None
            self.refresh()

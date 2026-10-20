"""The datasheet: rows of a table or query, editable in place like a spreadsheet."""
from __future__ import annotations

from PySide6.QtCore import (QAbstractTableModel, QDate, QModelIndex, QPoint, QSettings,
                            QSortFilterProxyModel, Qt, QTimer, Signal)
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QMessageBox, QStyledItemDelegate, QTableView, QToolButton, QVBoxLayout, QWidget,
)

from ...application.errors import ApplicationError, IncompleteRowError
from ...application.records import ColumnRecord
from ...application.types import FieldType, RowQuery
from ...application.workspace import PAGE, Source, Workspace
from .. import theme
from ..datasheet_format import edit_text, format_cell, format_money
from ..i18n import _, plural
from .common import icon_button

KEY_ROLE = Qt.UserRole + 1


def format_value(value, ftype: FieldType | None, currency: str = "") -> str:
    return format_cell(value, ftype, currency)


class DatasheetModel(QAbstractTableModel):
    problem = Signal(str)
    pendingChanged = Signal(str)  # a hint about the unfinished new row ("" when none)

    def __init__(self, workspace: Workspace, source: Source, editable: bool, parent=None):
        super().__init__(parent)
        self.ws = workspace
        self.source = source
        self.editable = editable and source.kind == "table"
        self.query = RowQuery()
        self.columns: list[ColumnRecord] = []
        self.rows: list = []
        self.total = 0
        self.labels: dict[int, dict] = {}  # column -> {key: label}
        self.pending: dict[str, str] = {}
        self.reload()

    # ---- loading ---------------------------------------------------------------------
    def reload(self, keep: int = 0):
        self.beginResetModel()
        try:
            want = max(PAGE, keep)
            page = self.ws.page(self.source, self.query, 0, want)
            self.columns = list(page.columns)
            self.rows = list(page.rows)
            self.total = page.total
            self.labels = {}
            for i, c in enumerate(self.columns):
                if c.ref_table:
                    table = self.ws.table(self.source.name)
                    ref = table.field(c.name).ref_field
                    self.labels[i] = {o.key: o.label for o in self.ws.lookup(c.ref_table, ref)}
        except ApplicationError as e:
            self.columns, self.rows, self.total, self.labels = [], [], 0, {}
            self.problem.emit(_(str(e)))
        self.endResetModel()

    def refresh(self):
        """Pick up changes without a reset when only values changed, so the cursor and the
        scroll position stay where they are."""
        keep = max(PAGE, len(self.rows))
        try:
            page = self.ws.page(self.source, self.query, 0, keep)
        except ApplicationError:
            self.reload(len(self.rows))
            return
        same_shape = (len(page.rows) == len(self.rows) and page.total == self.total
                      and [c.name for c in page.columns] == [c.name for c in self.columns]
                      and [r.key for r in page.rows] == [r.key for r in self.rows])
        if not same_shape:
            self.reload(len(self.rows))
            return
        self.rows = list(page.rows)
        for i, c in enumerate(self.columns):
            if c.ref_table:
                table = self.ws.table(self.source.name)
                ref = table.field(c.name).ref_field
                self.labels[i] = {o.key: o.label for o in self.ws.lookup(c.ref_table, ref)}
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1,
                                                                 len(self.columns) - 1))

    def canFetchMore(self, parent=QModelIndex()):
        return not parent.isValid() and len(self.rows) < self.total

    def fetchMore(self, parent=QModelIndex()):
        page = self.ws.page(self.source, self.query, len(self.rows), PAGE)
        if not page.rows:
            self.total = len(self.rows)
            return
        first = len(self.rows)
        self.beginInsertRows(QModelIndex(), first, first + len(page.rows) - 1)
        self.rows.extend(page.rows)
        self.endInsertRows()

    # ---- the model -------------------------------------------------------------------
    def _new_row(self) -> int:
        return len(self.rows)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows) + (1 if self.editable else 0)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.TextAlignmentRole:
            c = self.columns[section]
            numeric = c.type is not None and c.type.is_numeric and not c.ref_table
            return int((Qt.AlignRight if numeric else Qt.AlignLeft) | Qt.AlignVCenter)
        if orientation == Qt.Horizontal and role == Qt.ToolTipRole:
            c = self.columns[section]
            return c.name + (" — " + _("required") if c.required else "")
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            c = self.columns[section]
            return c.name + (" *" if c.required else "")
        return "✱" if self.editable and section == self._new_row() else str(section + 1)

    def _value(self, index):
        return self.rows[index.row()].values[index.column()]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        col = self.columns[index.column()]
        if index.row() == self._new_row() and self.editable:
            text = self.pending.get(col.name)
            if role in (Qt.DisplayRole, Qt.EditRole):
                if text is None:
                    return None if role == Qt.EditRole else ""
                if col.ref_table and role == Qt.DisplayRole:
                    return self._label(index.column(), text)
                return text
            if role == Qt.ForegroundRole:
                return None
            return None
        value = self._value(index)
        if role == Qt.CheckStateRole and col.type is FieldType.YES_NO:
            return Qt.Checked if value else Qt.Unchecked
        if role == Qt.DisplayRole:
            if col.type is FieldType.YES_NO:
                return ""
            if index.column() in self.labels and value is not None:
                return self.labels[index.column()].get(value, str(value))
            return format_value(value, col.type, col.currency)
        if role == Qt.ToolTipRole:
            shown = self.data(index, Qt.DisplayRole)
            return shown if shown and len(str(shown)) > 24 else None
        if role == Qt.EditRole:
            return edit_text(value, col.type)
        if role == Qt.TextAlignmentRole:
            numeric = col.type.is_numeric if col.type else isinstance(value, (int, float))
            return int(Qt.AlignRight | Qt.AlignVCenter) if numeric and not col.ref_table \
                else int(Qt.AlignLeft | Qt.AlignVCenter)
        if role == KEY_ROLE:
            return value
        return None

    def _label(self, column: int, text: str):
        try:
            key = int(text)
        except ValueError:
            return text
        return self.labels.get(column, {}).get(key, text)

    def flags(self, index):
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if not index.isValid() or not self.editable:
            return base
        col = self.columns[index.column()]
        if not col.editable:
            return base
        flags = base | Qt.ItemIsEditable
        if col.type is FieldType.YES_NO:
            flags |= Qt.ItemIsUserCheckable
        return flags

    def sort(self, column, order=Qt.AscendingOrder):
        if 0 <= column < len(self.columns):
            self.query = RowQuery(self.query.search, self.query.filters, self.columns[column].name,
                                  order == Qt.DescendingOrder)
            self.reload()

    def set_search(self, text: str):
        self.query = RowQuery(text, self.query.filters, self.query.order_by, self.query.descending)
        self.reload()

    def set_filters(self, filters):
        self.query = RowQuery(self.query.search, tuple(filters), self.query.order_by,
                              self.query.descending)
        self.reload()

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or not self.editable:
            return False
        col = self.columns[index.column()]
        if role == Qt.CheckStateRole:
            value = "yes" if Qt.CheckState(value) == Qt.Checked else "no"
        elif role != Qt.EditRole:
            return False
        text = "" if value is None else str(value)
        if index.row() == self._new_row():
            return self._set_pending(col.name, text)
        row = self.rows[index.row()]
        if text == edit_text(row.values[index.column()], col.type):
            return False
        try:
            self.ws.update_cell(self.source.name, row.key, col.name, text)
        except ApplicationError as e:
            self.problem.emit(_(str(e)))
            return False
        return True  # the workspace's DATA notice refreshes the sheet

    def _set_pending(self, name: str, text: str) -> bool:
        before = dict(self.pending)
        if text == "":
            self.pending.pop(name, None)
        else:
            self.pending[name] = text
        if not self.pending:
            self.pendingChanged.emit("")
            self._touch_new_row()
            return True
        try:
            self.ws.insert_row(self.source.name, self.pending)
        except IncompleteRowError:
            missing = [c.name for c in self.columns if c.required and c.name not in self.pending]
            self.pendingChanged.emit(_("Fill in the required fields to add this row: {fields}")
                                     .format(fields=", ".join(missing)))
            self._touch_new_row()
            return True
        except ApplicationError as e:
            self.pending = before
            self.problem.emit(_(str(e)))
            self._touch_new_row()
            return False
        self.pending = {}
        self.pendingChanged.emit("")
        return True

    def _touch_new_row(self):
        r = self._new_row()
        self.dataChanged.emit(self.index(r, 0), self.index(r, self.columnCount() - 1))

    def row_key(self, row: int):
        return self.rows[row].key if 0 <= row < len(self.rows) else None


class _ComboDelegate(QStyledItemDelegate):
    """A link to another table: pick the row it points at from a list."""

    def __init__(self, model: DatasheetModel, parent=None):
        super().__init__(parent)
        self.model = model

    def createEditor(self, parent, option, index):
        box = QComboBox(parent)
        box.addItem("", "")
        column = self.model.columns[index.column()]
        table = self.model.ws.table(self.model.source.name)
        for opt in self.model.ws.lookup(column.ref_table, table.field(column.name).ref_field):
            box.addItem(opt.label or str(opt.key), str(opt.key))
        return box

    def setEditorData(self, editor, index):
        i = editor.findData(str(index.data(Qt.EditRole) or ""))
        editor.setCurrentIndex(max(0, i))

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentData(), Qt.EditRole)


class _DateDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        edit = QLineEdit(parent)
        edit.setPlaceholderText(format_cell("2026-10-20", FieldType.DATE))
        return edit


class SheetView(QTableView):
    """A table view where Enter finishes an edit and moves down, like a spreadsheet."""

    def closeEditor(self, editor, hint):
        index = self.currentIndex()
        super().closeEditor(editor, hint)
        if hint == QStyledItemDelegate.SubmitModelCache and index.isValid():
            below = self.model().index(index.row() + 1, index.column())
            if below.isValid():
                self.setCurrentIndex(below)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.zoomRequested.emit(1 if event.angleDelta().y() > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)

    zoomRequested = Signal(int)


class Datasheet(QWidget):
    """Toolbar + grid. Editable for tables, read-only for query results."""

    problem = Signal(str)
    exportRequested = Signal()

    def __init__(self, workspace: Workspace, parent=None):
        super().__init__(parent)
        self.ws = workspace
        self.model: DatasheetModel | None = None
        self.editable = True
        self._filters: list[tuple[str, str, object, str]] = []  # column, op, value, caption

        self.search = QLineEdit(objectName="search", placeholderText=_("Search…"))
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(260)
        self._search_timer = QTimer(self, singleShot=True, interval=250)
        self._search_timer.timeout.connect(self._apply_search)
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        self.count = QLabel(objectName="muted")
        self.summary = QLabel(objectName="muted")  # sum / average of the selected numbers
        self.hint = QLabel(objectName="danger")
        self.hint.setWordWrap(True)
        self.hint.hide()
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        self.undo_button = icon_button("undo", _("Undo (Ctrl+Z)"))
        self.redo_button = icon_button("redo", _("Redo (Ctrl+Shift+Z)"))
        self.delete_button = icon_button("trash", _("Delete the selected rows (Delete)"))
        self.export_button = icon_button("download", _("Export as CSV…"))
        self.fit_button = icon_button("fit", _("Fit the columns to their contents"))
        self.fit_button.clicked.connect(self.fit_columns)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.delete_button.clicked.connect(self.delete_selected_rows)
        self.export_button.clicked.connect(self.exportRequested)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(self.search)
        bar.addLayout(self.chips)
        bar.addStretch()
        bar.addWidget(self.summary)
        bar.addSpacing(14)
        bar.addWidget(self.count)
        bar.addSpacing(10)
        for b in (self.fit_button, self.undo_button, self.redo_button, self.delete_button,
                  self.export_button):
            bar.addWidget(b)

        self.view = SheetView()
        self.view.setObjectName("datasheet")
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                  | QAbstractItemView.AnyKeyPressed)
        self.view.setSortingEnabled(True)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.view.horizontalHeader().setHighlightSections(False)
        self.view.horizontalHeader().setSectionsMovable(False)
        self.zoom = self._saved_zoom()
        self._apply_zoom()
        self.view.verticalHeader().setMinimumWidth(34)
        self.view.zoomRequested.connect(lambda step: self.set_zoom(self.zoom + step * 10))
        self.view.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.setWordWrap(False)
        self.view.setTextElideMode(Qt.ElideRight)
        self.view.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.view.horizontalHeader().setMinimumSectionSize(48)
        self.view.horizontalHeader().sectionResized.connect(self._remember_width)
        self._width_timer = QTimer(self, singleShot=True, interval=400)
        self._width_timer.timeout.connect(self._save_widths)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._menu)
        self.view.setShowGrid(True)
        self.empty = QLabel(objectName="hint", alignment=Qt.AlignCenter)
        self.empty.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(bar)
        layout.addWidget(self.hint)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.empty)
        self.ws.subscribe(self._changed)
        self._update_buttons()

    # ---- loading ---------------------------------------------------------------------
    def show_source(self, source: Source | None, editable: bool = True):
        self.editable = editable
        self._filters.clear()
        self._rebuild_chips()
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.hint.hide()
        if source is None:
            self.model = None
            self.view.setModel(None)
            self._update_buttons()
            return
        self.model = DatasheetModel(self.ws, source, editable, self)
        self.model.problem.connect(self._problem)
        self.model.pendingChanged.connect(self._pending)
        self.model.modelReset.connect(self._after_reload)
        self.view.setModel(self.model)
        self.view.horizontalHeader().setSortIndicatorShown(True)
        self.view.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        for i, c in enumerate(self.model.columns):
            if c.ref_table and editable:
                self.view.setItemDelegateForColumn(i, _ComboDelegate(self.model, self.view))
            elif c.type in (FieldType.DATE, FieldType.DATETIME):
                self.view.setItemDelegateForColumn(i, _DateDelegate(self.view))
        self.view.selectionModel().selectionChanged.connect(lambda *_a: self._update_summary())
        self.fit_columns()
        self._restore_widths()
        self.export_button.setEnabled(True)
        self.summary.setText("")
        self._after_reload()
        self._update_buttons()

    def _after_reload(self):
        m = self.model
        if m is None:
            return
        self.count.setText(plural(m.total, "row"))
        self.empty.setVisible(m.total == 0 and not m.editable)
        self.empty.setText(_("No rows match.") if self.search.text() or self._filters
                           else _("This query has no rows."))
        self._update_buttons()

    def _changed(self, change):
        from ...application.workspace import Change
        if change is Change.DATA and self.model is not None and self.isVisible():
            QTimer.singleShot(0, self.refresh)  # not inside the edit that caused it
        self._update_buttons()

    def refresh(self):
        if self.model is not None:
            self.model.refresh()

    # ---- searching and filtering ---------------------------------------------------------
    def _apply_search(self):
        if self.model is not None:
            self.model.set_search(self.search.text())

    def _apply_filters(self):
        if self.model is not None:
            self.model.set_filters([(c, op, v) for c, op, v, _cap in self._filters])
        self._rebuild_chips()

    def _rebuild_chips(self):
        while self.chips.count():
            item = self.chips.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, (_c, _op, _v, caption) in enumerate(self._filters):
            chip = QToolButton(objectName="tool", text=f"{caption}  ✕")
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _c=False, i=i: self._remove_filter(i))
            self.chips.addWidget(chip)

    def _remove_filter(self, i: int):
        del self._filters[i]
        self._apply_filters()

    def _add_filter(self, column: str, op: str, value, caption: str):
        self._filters.append((column, op, value, caption))
        self._apply_filters()

    def _menu(self, pos: QPoint):
        m = self.model
        if m is None:
            return
        index = self.view.indexAt(pos)
        menu = QMenu(self)
        if index.isValid() and index.row() < len(m.rows):
            col = m.columns[index.column()]
            value = m.rows[index.row()].values[index.column()]
            shown = index.data(Qt.DisplayRole) or index.data(Qt.CheckStateRole)
            if value is None or value == "":
                menu.addAction(_("Show only empty {field}").format(field=col.name),
                               lambda: self._add_filter(col.name, "null", None,
                                                        _("{field} is empty").format(field=col.name)))
            else:
                menu.addAction(_("Show only this value"), lambda: self._add_filter(
                    col.name, "=", value, f"{col.name} = {shown}"))
                menu.addAction(_("Hide this value"), lambda: self._add_filter(
                    col.name, "<>", value, f"{col.name} ≠ {shown}"))
            menu.addAction(_("Show only filled {field}").format(field=col.name),
                           lambda: self._add_filter(col.name, "notnull", None,
                                                    _("{field} is filled").format(field=col.name)))
            menu.addSeparator()
            menu.addAction(_("Copy"), self.copy)
            if m.editable:
                menu.addAction(_("Delete row"), self.delete_selected_rows)
        if self._filters:
            menu.addSeparator()
            menu.addAction(_("Clear filters"), self._clear_filters)
        if menu.actions():
            menu.exec(self.view.viewport().mapToGlobal(pos))

    def _clear_filters(self):
        self._filters.clear()
        self._apply_filters()

    # ---- editing -------------------------------------------------------------------
    def _selected_rows(self) -> list[int]:
        m = self.model
        if m is None:
            return []
        return sorted({i.row() for i in self.view.selectionModel().selectedIndexes()
                       if i.row() < len(m.rows)})

    def delete_selected_rows(self):
        m = self.model
        rows = self._selected_rows()
        if m is None or not m.editable or not rows:
            return
        answer = QMessageBox.question(
            self, _("Delete rows"),
            _("Delete {rows}? You can undo this.").format(rows=plural(len(rows), "row")))
        if answer != QMessageBox.Yes:
            return
        try:
            self.ws.delete_rows(m.source.name, [m.row_key(r) for r in rows])
        except ApplicationError as e:
            self._problem(_(str(e)))

    def clear_selected_cells(self):
        m = self.model
        if m is None or not m.editable:
            return
        for index in self.view.selectionModel().selectedIndexes():
            if index.row() < len(m.rows) and m.flags(index) & Qt.ItemIsEditable:
                m.setData(index, "", Qt.EditRole)

    def keyPressEvent(self, event):
        if self.view.hasFocus() and event.key() in (Qt.Key_Delete, Qt.Key_Backspace) \
                and self.model is not None and self.model.editable \
                and self.view.state() != QAbstractItemView.EditingState:
            selection = self.view.selectionModel()
            full_rows = selection.selectedRows()
            if full_rows:
                self.delete_selected_rows()
            else:
                self.clear_selected_cells()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() in (Qt.Key_Plus, Qt.Key_Equal):
            self.set_zoom(self.zoom + 10)
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_Minus:
            self.set_zoom(self.zoom - 10)
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_0:
            self.set_zoom(115)
            return
        if event.matches(QKeySequence.Copy) and self.view.hasFocus():
            self.copy()
            return
        super().keyPressEvent(event)

    def copy(self):
        indexes = sorted(self.view.selectionModel().selectedIndexes(),
                         key=lambda i: (i.row(), i.column()))
        if not indexes:
            return
        lines, row, cells = [], indexes[0].row(), []
        for i in indexes:
            if i.row() != row:
                lines.append("\t".join(cells))
                cells, row = [], i.row()
            cells.append(str(i.data(Qt.DisplayRole) or ""))
        lines.append("\t".join(cells))
        QGuiApplication.clipboard().setText("\n".join(lines))

    def focus_new_row(self):
        m = self.model
        if m is None or not m.editable:
            return
        row = m.rowCount() - 1
        for c, col in enumerate(m.columns):
            if col.editable:
                self.view.setCurrentIndex(m.index(row, c))
                self.view.edit(m.index(row, c))
                break

    # ---- comfort: widths, zoom, summary ------------------------------------------------
    def _settings_key(self) -> str:
        from pathlib import Path
        m = self.model
        return f"sheet/{Path(self.ws.path or '').name}/{m.source.kind}:{m.source.name[:60]}" if m else ""

    def fit_columns(self):
        """Make every column as wide as its contents (within reason)."""
        if self.model is None:
            return
        self.view.resizeColumnsToContents()
        header = self.view.horizontalHeader()
        for i in range(self.model.columnCount()):
            header.resizeSection(i, max(72, min(header.sectionSize(i) + 14, 340)))
        header.setStretchLastSection(True)
        self._save_widths()

    def _restore_widths(self):
        key = self._settings_key()
        saved = QSettings().value(key + "/widths") if key else None
        if not isinstance(saved, (list, tuple)) or self.model is None:
            return
        try:
            widths = [int(w) for w in saved]
        except (TypeError, ValueError):
            return
        if len(widths) == self.model.columnCount():
            for i, w in enumerate(widths):
                self.view.horizontalHeader().resizeSection(i, w)

    def _remember_width(self, *_args):
        self._width_timer.start()

    def _save_widths(self):
        key = self._settings_key()
        if key and self.model is not None:
            h = self.view.horizontalHeader()
            QSettings().setValue(key + "/widths", [h.sectionSize(i) for i in range(h.count())])

    def _saved_zoom(self) -> int:
        try:
            return max(70, min(200, int(QSettings().value("sheet/zoom", 115))))
        except (TypeError, ValueError):
            return 115

    def set_zoom(self, percent: int):
        self.zoom = max(70, min(200, percent))
        QSettings().setValue("sheet/zoom", self.zoom)
        self._apply_zoom()

    def _apply_zoom(self):
        font = self.view.font()
        base = QGuiApplication.font().pointSizeF()
        font.setPointSizeF(base * self.zoom / 100 if base > 0 else 10 * self.zoom / 100)
        self.view.setFont(font)
        self.view.verticalHeader().setDefaultSectionSize(round(32 * self.zoom / 100))

    def _update_summary(self):
        """Sum and average of the selected numbers, like a spreadsheet's status bar."""
        m = self.model
        if m is None:
            return
        values, codes, columns = [], set(), set()
        for index in self.view.selectionModel().selectedIndexes():
            if index.row() >= len(m.rows):
                continue
            col = m.columns[index.column()]
            v = m.rows[index.row()].values[index.column()]
            if isinstance(v, (int, float)) and not isinstance(v, bool) and not col.ref_table \
                    and (col.type is None or col.type.is_numeric):
                values.append(float(v))
                columns.add(index.column())
                codes.add(col.currency if col.type is FieldType.CURRENCY else "")
        if len(values) < 2:
            self.summary.setText("")
            return
        total = sum(values)
        money = len(codes) == 1 and next(iter(codes))
        fmt = (lambda x: format_money(x, money)) if money else (lambda x: format_cell(x, None))
        self.summary.setText(_("Sum {sum} · Average {avg} · {n} cells").format(
            sum=fmt(total), avg=fmt(total / len(values)), n=len(values)))

    def undo(self):
        self._run(self.ws.undo)

    def redo(self):
        self._run(self.ws.redo)

    def _run(self, action):
        try:
            action()
        except ApplicationError as e:
            self._problem(_(str(e)))

    def _update_buttons(self):
        editable = self.model is not None and self.model.editable
        self.undo_button.setEnabled(editable and self.ws.can_undo)
        self.redo_button.setEnabled(editable and self.ws.can_redo)
        self.delete_button.setEnabled(editable)
        self.export_button.setEnabled(self.model is not None)
        self.fit_button.setEnabled(self.model is not None)

    def _problem(self, text: str):
        self.hint.setText(text)
        self.hint.show()
        QTimer.singleShot(6000, self.hint.hide)
        self.problem.emit(text)

    def _pending(self, text: str):
        if text:
            self.hint.setText(text)
            self.hint.show()
        else:
            self.hint.hide()

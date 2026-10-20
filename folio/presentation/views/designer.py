"""The table designer: name, fields, keys and links."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...application.inputs import FieldDesign, TableDesign
from ...application.records import TableRecord
from ...application.types import DEFAULT_CURRENCY, FieldType, ON_DELETE, currency_symbol
from ...application.workspace import Workspace
from .. import theme
from ..i18n import N_, _, Translated
from .common import button, icon_button, label, primary_button

TYPE_NAMES = Translated({
    FieldType.TEXT: N_("Text"), FieldType.LONG_TEXT: N_("Long text"),
    FieldType.INTEGER: N_("Whole number"), FieldType.NUMBER: N_("Number"),
    FieldType.CURRENCY: N_("Currency"),
    FieldType.YES_NO: N_("Yes/No"), FieldType.DATE: N_("Date"),
    FieldType.DATETIME: N_("Date and time"),
})
DELETE_NAMES = Translated({"NO ACTION": N_("Block"), "CASCADE": N_("Delete linked rows"),
                           "SET NULL": N_("Clear the link")})

CURRENCY_CHOICES = ("EUR", "USD", "GBP", "CHF", "RUB", "JPY", "PLN")


def fill_type_combo(box: QComboBox) -> None:
    """Field types, with one entry per currency ("Currency € EUR")."""
    for ftype, text in TYPE_NAMES.items():
        if ftype is not FieldType.CURRENCY:
            box.addItem(text, ftype.value)
    for code in CURRENCY_CHOICES:
        box.addItem(f"{TYPE_NAMES[FieldType.CURRENCY]} {currency_symbol(code)} {code}",
                    f"currency:{code}")


def type_key(ftype: FieldType, currency: str = "") -> str:
    return f"currency:{currency or DEFAULT_CURRENCY}" if ftype is FieldType.CURRENCY else ftype.value


def from_type_key(key: str) -> tuple[FieldType, str]:
    if key.startswith("currency:"):
        return FieldType.CURRENCY, key.partition(":")[2]
    return FieldType(key), ""


def select_type(box: QComboBox, ftype: FieldType, currency: str = "") -> None:
    key = type_key(ftype, currency)
    i = box.findData(key)
    if i < 0 and ftype is FieldType.CURRENCY:  # a currency outside the short list
        box.addItem(f"{TYPE_NAMES[FieldType.CURRENCY]} {currency_symbol(currency)} {currency}", key)
        i = box.count() - 1
    box.setCurrentIndex(max(0, i))


NAME, TYPE, KEY, AUTO, REQUIRED, UNIQUE, DEFAULT, LINK, ON_DEL = range(9)


def design_of(record: TableRecord) -> TableDesign:
    return TableDesign(record.name, tuple(
        FieldDesign(f.name, f.type, f.primary_key, f.autonumber, f.required, f.unique,
                    f.default, f.currency, f.name, f.ref_table, f.ref_field, f.on_delete)
        for f in record.fields))


def _center(widget: QWidget) -> QWidget:
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setAlignment(Qt.AlignCenter)
    row.addWidget(widget)
    holder.check = widget
    return holder


class TableDesigner(QWidget):
    saved = Signal(str)  # the table's name after saving
    discarded = Signal()

    def __init__(self, workspace: Workspace, parent=None):
        super().__init__(parent)
        self.ws = workspace
        self.original: str | None = None
        self._loading = False

        self.name = QLineEdit(objectName="titleEdit", placeholderText=_("Table name"))
        self.grid = QTableWidget(0, 9)
        self.grid.setHorizontalHeaderLabels([
            _("Field"), _("Type"), _("Key"), _("Auto"), _("Required"), _("Unique"),
            _("Default"), _("Links to"), _("If the other row is deleted")])
        self.grid.verticalHeader().setVisible(False)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.grid.setSelectionMode(QAbstractItemView.SingleSelection)
        header = self.grid.horizontalHeader()
        for col, width in ((NAME, 170), (TYPE, 170), (KEY, 54), (AUTO, 54), (REQUIRED, 74),
                           (UNIQUE, 66), (DEFAULT, 100), (LINK, 150)):
            header.setSectionResizeMode(col, QHeaderView.Fixed)
            self.grid.setColumnWidth(col, width)
        header.setSectionResizeMode(ON_DEL, QHeaderView.Stretch)
        self.grid.verticalHeader().setDefaultSectionSize(36)

        self.add = button(_("Add field"), "plus")
        self.remove = button(_("Remove field"), "trash")
        self.up = icon_button("chevron-up", _("Move up"))
        self.down = icon_button("chevron-down", _("Move down"))
        self.save = primary_button(_("Save changes"), "check")
        self.discard = button(_("Discard"))
        self.message = QLabel(objectName="danger")
        self.message.setWordWrap(True)
        self.message.hide()
        self.note = label("", "hint")
        self.note.setWordWrap(True)

        self.add.clicked.connect(lambda: self.add_field())
        self.remove.clicked.connect(self.remove_field)
        self.up.clicked.connect(lambda: self.move(-1))
        self.down.clicked.connect(lambda: self.move(1))
        self.save.clicked.connect(self.apply)
        self.discard.clicked.connect(self.discarded)

        tools = QHBoxLayout()
        tools.setSpacing(6)
        tools.addWidget(self.add)
        tools.addWidget(self.remove)
        tools.addWidget(self.up)
        tools.addWidget(self.down)
        tools.addStretch()
        tools.addWidget(self.discard)
        tools.addWidget(self.save)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.name)
        layout.addLayout(tools)
        layout.addWidget(self.message)
        layout.addWidget(self.grid, 1)
        layout.addWidget(self.note)

    # ---- loading ---------------------------------------------------------------------
    def load(self, record: TableRecord | None):
        """Show an existing table, or a blank design for a new one."""
        self._loading = True
        self.original = record.name if record else None
        self.name.setText(record.name if record else "")
        self.grid.setRowCount(0)
        self.message.hide()
        locked = bool(record and record.locked)
        for w in (self.name, self.grid, self.add, self.remove, self.up, self.down, self.save):
            w.setEnabled(not locked)
        self.note.setText(
            _("This table uses features the designer can't keep (such as checks or composite "
              "keys), so only its rows can be edited here.") if locked else
            _("Key marks the field that identifies each row. Auto counts up by itself. "
              "“Links to” makes the field point at another table's key, so you can pick from a list."))
        if record:
            for d in design_of(record).fields:
                self.add_field(d)
        else:
            self.add_field(FieldDesign("id", FieldType.INTEGER, True, True))
            self.add_field(FieldDesign(""))
        self._loading = False
        self.name.setFocus()

    def _link_options(self) -> list[tuple[str, str, str]]:
        """Every key field of the tables (and of this table), as (text, table, field)."""
        options = []
        for t in self.ws.tables():
            if t.name == self.original:
                continue
            for f in t.fields:
                if f.primary_key or f.unique:
                    options.append((f"{t.name} → {f.name}", t.name, f.name))
        return options

    def add_field(self, d: FieldDesign | None = None):
        d = d or FieldDesign("")
        row = self.grid.rowCount()
        self.grid.insertRow(row)
        item = QTableWidgetItem(d.name)
        item.setData(Qt.UserRole, d.original_name)
        self.grid.setItem(row, NAME, item)
        types = QComboBox()
        fill_type_combo(types)
        select_type(types, d.type, d.currency)
        self.grid.setCellWidget(row, TYPE, types)
        for col, value in ((KEY, d.primary_key or d.autonumber), (AUTO, d.autonumber),
                           (REQUIRED, d.required), (UNIQUE, d.unique)):
            box = QCheckBox()
            box.setChecked(value)
            self.grid.setCellWidget(row, col, _center(box))
        default = QTableWidgetItem(d.default)
        self.grid.setItem(row, DEFAULT, default)
        link = QComboBox()
        link.addItem(_("(none)"), None)
        for text, table, field in self._link_options():
            link.addItem(text, f"{table}\t{field}")
        if d.ref_table:
            i = link.findData(f"{d.ref_table}\t{d.ref_field}")
            if i < 0:  # a link to this very table, or one we can't offer
                link.addItem(f"{d.ref_table} → {d.ref_field}", f"{d.ref_table}\t{d.ref_field}")
                i = link.count() - 1
            link.setCurrentIndex(i)
        self.grid.setCellWidget(row, LINK, link)
        action = QComboBox()
        for value in ON_DELETE:
            action.addItem(DELETE_NAMES[value], value)
        action.setCurrentIndex(max(0, action.findData(d.on_delete)))
        self.grid.setCellWidget(row, ON_DEL, action)
        self._wire(row)
        self.grid.setCurrentCell(row, NAME)
        if not self._loading:
            self.grid.editItem(item)

    def _wire(self, row: int):
        key = self._box(row, KEY)
        auto = self._box(row, AUTO)
        types = self.grid.cellWidget(row, TYPE)

        def sync():
            if auto.isChecked():
                key.setChecked(True)
                types.setCurrentIndex(types.findData("integer"))
            auto.setEnabled(types.currentData() == "integer")
            if not auto.isEnabled():
                auto.setChecked(False)

        auto.toggled.connect(lambda _c: sync())
        types.currentIndexChanged.connect(lambda _i: sync())
        sync()

    def _box(self, row: int, col: int) -> QCheckBox:
        return self.grid.cellWidget(row, col).check

    def remove_field(self):
        row = self.grid.currentRow()
        if row >= 0:
            self.grid.removeRow(row)

    def move(self, step: int):
        row = self.grid.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.grid.rowCount():
            return
        fields = self.fields()
        fields[row], fields[target] = fields[target], fields[row]
        self._loading = True
        self.grid.setRowCount(0)
        for f in fields:
            self.add_field(f)
        self._loading = False
        self.grid.setCurrentCell(target, NAME)

    # ---- reading ---------------------------------------------------------------------
    def fields(self) -> list[FieldDesign]:
        result = []
        for row in range(self.grid.rowCount()):
            item = self.grid.item(row, NAME)
            link = self.grid.cellWidget(row, LINK).currentData()
            ftype, currency = from_type_key(self.grid.cellWidget(row, TYPE).currentData())
            result.append(FieldDesign(
                item.text().strip(), ftype,
                self._box(row, KEY).isChecked(), self._box(row, AUTO).isChecked(),
                self._box(row, REQUIRED).isChecked(), self._box(row, UNIQUE).isChecked(),
                (self.grid.item(row, DEFAULT).text() if self.grid.item(row, DEFAULT) else "").strip(),
                currency, item.data(Qt.UserRole), *(link.split("\t") if link else ("", "")),
                self.grid.cellWidget(row, ON_DEL).currentData()))
        return result

    def design(self) -> TableDesign:
        return TableDesign(self.name.text().strip(),
                           tuple(f for f in self.fields() if f.name))

    def apply(self):
        from ...application.errors import ApplicationError
        name = self.name.text().strip()  # read first: saving makes the page reload this designer
        try:
            self.ws.save_table(self.original, self.design())
        except ApplicationError as e:
            self.message.setText(_(str(e)))
            self.message.show()
            return
        self.message.hide()
        self.saved.emit(name)

"""A page with a list of objects (tables, queries, forms…) on the left and the open one on the right."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QStackedWidget, QVBoxLayout, QWidget,
)

from .. import icons, theme
from ..i18n import _
from .common import Card, Page, button, icon_button, label, primary_button


class ObjectList(Card):
    chosen = Signal(str)  # a name, or "" when nothing is chosen
    newRequested = Signal()

    def __init__(self, title: str, new_text: str, icon_name: str, parent=None):
        super().__init__(None, 12, parent)
        self.setFixedWidth(236)
        self.icon_name = icon_name
        self.new = primary_button(new_text, "plus")
        self.search = None
        self.list = QListWidget(objectName="recent")
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setSpacing(1)
        self.empty = label("", "hint")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignCenter)
        self.body.addWidget(self.new)
        self.body.addWidget(self.list, 1)
        self.body.addWidget(self.empty)
        self.new.clicked.connect(self.newRequested)
        self.list.currentItemChanged.connect(
            lambda cur, _prev: self.chosen.emit(cur.data(Qt.UserRole) if cur else ""))

    def set_items(self, items: list[tuple[str, str]], current: str | None = None,
                  empty_text: str = ""):
        """items: (name, detail)."""
        self.list.blockSignals(True)
        self.list.clear()
        for name, detail in items:
            item = QListWidgetItem(f"{name}\n{detail}" if detail else name)
            item.setData(Qt.UserRole, name)
            theme.themed(lambda t, item=item: item.setIcon(
                icons.icon(self.icon_name, t.muted, size=18)))
            self.list.addItem(item)
            if name == current:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self.empty.setText(empty_text)
        self.empty.setVisible(not items)
        self.list.setVisible(bool(items))
        if current is None or not any(n == current for n, _d in items):
            self.chosen.emit("")
        else:
            self.chosen.emit(current)

    def current(self) -> str:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else ""


class ObjectPage(Page):
    """Header, a list of objects, and a stack with an empty state and the editor."""

    def __init__(self, title: str, subtitle: str, new_text: str, icon_name: str, empty_hint: str,
                 parent=None):
        super().__init__(parent)
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.empty_hint = empty_hint
        self.items = ObjectList(title, new_text, icon_name)
        self.stack = QStackedWidget()
        self.placeholder = Card(None, 24)
        hint = label(empty_hint, "hint")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        self.placeholder.body.addStretch()
        self.placeholder.body.addWidget(hint)
        self.placeholder.body.addStretch()
        self.stack.addWidget(self.placeholder)
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(self.items)
        row.addWidget(self.stack, 1)
        self.root.addLayout(row, 1)

    def add_view(self, widget: QWidget) -> QWidget:
        self.stack.addWidget(widget)
        return widget

    def confirm_delete(self, what: str, name: str) -> bool:
        return QMessageBox.question(
            self, what, _("Delete “{name}”? This can't be undone.").format(name=name)
        ) == QMessageBox.Yes


class Header(QFrame):
    """Title of the open object, with a place for its controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.title = QLabel(objectName="sheetTitle")
        self.title.setMinimumWidth(80)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(8)
        self.row.addWidget(self.title)
        self.row.addStretch()

    def add(self, widget):
        self.row.addWidget(widget)
        return widget

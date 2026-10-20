"""The start page: new database, open one, convert an Access file, recent files."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout, QListWidget, QListWidgetItem, QSizePolicy, QToolButton,
)

from .. import theme
from ..i18n import _
from .common import Card, Page, button, label


class HomePage(Page):
    newRequested = Signal()
    openRequested = Signal(str)  # a path, or "" to choose one
    sampleRequested = Signal()
    accessRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.title.setText(_("Folio"))
        self.subtitle.setText(_("Tables, queries, forms and reports, in one file you can keep."))

        start = Card(_("Start"))
        grid = QGridLayout()
        grid.setSpacing(10)
        for column, (icon, text, detail, action) in enumerate((
                ("plus", _("New database"), _("An empty .folio file"),
                 lambda: self.newRequested.emit()),
                ("folder", _("Open…"), _("A .folio, .db or .sqlite file"),
                 lambda: self.openRequested.emit("")),
                ("upload", _("From Access…"), _("Bring in an .accdb or .mdb file"),
                 lambda: self.accessRequested.emit()))):
            tile = QToolButton(objectName="startTile")
            tile.setText(f"{text}\n{detail}")
            tile.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            tile.setIconSize(QSize(30, 30))
            tile.setMinimumSize(210, 120)
            tile.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            tile.setCursor(Qt.PointingHandCursor)
            theme.set_icon(tile, icon, "accent", size=30)
            tile.clicked.connect(action)
            grid.addWidget(tile, 0, column)
        start.body.addLayout(grid)
        start.add(label(_("Or look around a sample first:"), "hint"))
        sample = button(_("School library"), "database")
        sample.clicked.connect(lambda: self.sampleRequested.emit())
        start.add(sample)

        self.recent_card = Card(_("Recent"))
        self.recent = QListWidget(objectName="recent")
        self.recent.itemActivated.connect(lambda item: self.openRequested.emit(item.data(Qt.UserRole)))
        self.recent.itemClicked.connect(lambda item: self.openRequested.emit(item.data(Qt.UserRole)))
        self.recent_card.add(self.recent, 1)
        self.root.addWidget(start)
        self.root.addWidget(self.recent_card, 1)

    def set_recent(self, paths: list[str]):
        self.recent.clear()
        for p in paths:
            item = QListWidgetItem(f"{Path(p).name}\n{Path(p).parent}")
            item.setData(Qt.UserRole, p)
            self.recent.addItem(item)
        self.recent_card.setVisible(bool(paths))

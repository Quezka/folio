"""The relationships diagram: tables as boxes, links as lines."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QGraphicsItem, QGraphicsPathItem, QGraphicsScene,
    QGraphicsView, QHBoxLayout, QMenu, QMessageBox, QVBoxLayout,
)

from ...application.errors import ApplicationError
from ...application.inputs import FieldDesign
from ...application.records import TableRecord
from ...application.workspace import Change, Workspace
from .. import theme
from ..i18n import _
from .common import Card, Page, button, label, primary_button
from .designer import design_of

WIDTH, HEAD, ROW = 190, 32, 22


class TableItem(QGraphicsItem):
    def __init__(self, record: TableRecord, on_moved):
        super().__init__()
        self.record = record
        self.on_moved = on_moved
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges
                      | QGraphicsItem.ItemIsSelectable)
        self.setCursor(Qt.OpenHandCursor)
        self.links: list[LinkItem] = []

    def boundingRect(self):
        return QRectF(0, 0, WIDTH, HEAD + ROW * max(1, len(self.record.fields)) + 8)

    def row_y(self, field: str) -> float:
        for i, f in enumerate(self.record.fields):
            if f.name == field:
                return HEAD + ROW * i + ROW / 2
        return HEAD / 2

    def paint(self, p: QPainter, option, widget=None):
        t = theme.current()
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.boundingRect()
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        p.fillPath(path, QColor(t.surface))
        p.setPen(QPen(QColor(t.accent if self.isSelected() else t.border), 1.5))
        p.drawPath(path)
        head = QPainterPath()
        head.setFillRule(Qt.WindingFill)
        head.addRoundedRect(QRectF(0, 0, WIDTH, HEAD), 10, 10)
        head.addRect(QRectF(0, HEAD - 10, WIDTH, 10))
        p.save()
        p.setClipPath(path)
        p.fillPath(head, QColor(t.accent_soft))
        p.restore()
        font = QFont(p.font())
        font.setPixelSize(13)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(t.text))
        p.drawText(QRectF(12, 0, WIDTH - 24, HEAD), Qt.AlignVCenter | Qt.AlignLeft,
                   self.record.name)
        font.setBold(False)
        font.setPixelSize(12)
        p.setFont(font)
        for i, f in enumerate(self.record.fields):
            y = HEAD + ROW * i
            p.setPen(QColor(t.accent if f.primary_key else t.text))
            marker = "PK  " if f.primary_key else ("FK  " if f.ref_table else "      ")
            p.drawText(QRectF(10, y, WIDTH - 20, ROW), Qt.AlignVCenter | Qt.AlignLeft,
                       f"{marker}{f.name}")

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            for link in self.links:
                link.update_path()
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.on_moved()


class LinkItem(QGraphicsPathItem):
    def __init__(self, child: TableItem, child_field: str, parent: TableItem, parent_field: str,
                 meta):
        super().__init__()
        self.child, self.child_field = child, child_field
        self.parent_item, self.parent_field = parent, parent_field
        self.meta = meta
        self.setZValue(-1)
        self.setAcceptHoverEvents(True)
        child.links.append(self)
        if parent is not child:
            parent.links.append(self)
        self.update_path()

    def update_path(self):
        t = theme.current()
        a, b = self.child, self.parent_item
        ya = a.pos().y() + a.row_y(self.child_field)
        yb = b.pos().y() + b.row_y(self.parent_field)
        a_right = a.pos().x() + WIDTH / 2 < b.pos().x() + WIDTH / 2
        xa = a.pos().x() + (WIDTH if a_right else 0)
        xb = b.pos().x() + (0 if a_right else WIDTH)
        if a is b:
            xa, xb = a.pos().x() + WIDTH, a.pos().x() + WIDTH
        path = QPainterPath(QPointF(xa, ya))
        if a is b:
            path.lineTo(xa + 36, ya)
            path.lineTo(xa + 36, yb)
        else:
            sign = 1 if a_right else -1
            path.lineTo(xa + sign * 18, ya)
            path.lineTo(xb - sign * 18, yb)
        path.lineTo(xb, yb)
        self.prepareGeometryChange()
        self.setPath(path)
        self.setPen(QPen(QColor(t.accent), 1.6))

    def paint(self, p, option, widget=None):
        super().paint(p, option, widget)
        t = theme.current()
        p.setRenderHint(QPainter.Antialiasing)
        path = self.path()
        font = QFont(p.font())
        font.setPixelSize(12)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(t.accent))
        p.drawText(path.pointAtPercent(0) + QPointF(-4, -6), "∞")
        p.drawText(path.pointAtPercent(1) + QPointF(-4, -6), "1")

    def boundingRect(self):
        return super().boundingRect().adjusted(-24, -24, 24, 24)

    def shape(self):
        from PySide6.QtGui import QPainterPathStroker
        stroker = QPainterPathStroker()
        stroker.setWidth(12)
        return stroker.createStroke(self.path())


class RelationsView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        theme.themed(lambda t: self.setBackgroundBrush(QBrush(QColor(t.raised))))

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
        else:
            super().wheelEvent(event)


class LinkDialog(QDialog):
    def __init__(self, ws: Workspace, parent=None):
        super().__init__(parent)
        self.ws = ws
        self.setWindowTitle(_("Link tables"))
        self.child = QComboBox()
        self.field = QComboBox()
        self.parent_key = QComboBox()
        self.action = QComboBox()
        for text, value in ((_("Block"), "NO ACTION"), (_("Delete linked rows"), "CASCADE"),
                            (_("Clear the link"), "SET NULL")):
            self.action.addItem(text, value)
        for t in ws.tables():
            self.child.addItem(t.name, t)
            for f in t.fields:
                if f.primary_key or f.unique:
                    self.parent_key.addItem(f"{t.name} → {f.name}", (t.name, f.name))
        self.child.currentIndexChanged.connect(self._fields)
        self._fields()
        ok, cancel = primary_button(_("Link"), "check"), button(_("Cancel"))
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        form = QFormLayout()
        form.addRow(_("Table with the field"), self.child)
        form.addRow(_("Field"), self.field)
        form.addRow(_("Points at"), self.parent_key)
        form.addRow(_("If the other row is deleted"), self.action)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(ok)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.addWidget(label(_("Many rows of one table can point at one row of another, "
                                 "for example many orders at one customer."), "hint"))
        layout.addLayout(form)
        layout.addLayout(row)
        self.setMinimumWidth(420)

    def _fields(self):
        table = self.child.currentData()
        self.field.clear()
        if table:
            for f in table.fields:
                self.field.addItem(f.name, f.name)


class RelationsPage(Page):
    def __init__(self, workspace: Workspace, parent=None):
        super().__init__(parent)
        self.ws = workspace
        self.title.setText(_("Relationships"))
        self.subtitle.setText(_("How your tables point at each other. Drag the boxes to arrange them."))
        self.link_button = primary_button(_("Link tables…"), "link")
        self.fit_button = button(_("Fit"), "fit")
        self.add_actions(self.fit_button, self.link_button)
        self.scene = QGraphicsScene(self)
        self.view = RelationsView()
        self.view.setScene(self.scene)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._menu)
        card = Card(None, 0)
        card.add(self.view, 1)
        self.empty = label(_("Tables you link will show up here."), "hint")
        self.empty.setAlignment(Qt.AlignCenter)
        self.root.addWidget(card, 1)
        self.root.addWidget(self.empty)
        self.items: dict[str, TableItem] = {}
        self.link_button.clicked.connect(self.link_tables)
        self.fit_button.clicked.connect(self.fit)
        workspace.subscribe(self._changed)
        theme.manager().changed.connect(lambda _t: self.scene.update())

    def _changed(self, change):
        if change in (Change.OPENED, Change.CLOSED, Change.SCHEMA):
            self.rebuild()

    def rebuild(self):
        self.scene.clear()
        self.items = {}
        if not self.ws.is_open:
            self.empty.show()
            return
        tables = self.ws.tables()
        saved = self.ws.layout()
        self.empty.setVisible(not tables)
        x = y = 0
        for i, t in enumerate(tables):
            item = TableItem(t, self.save_positions)
            pos = saved.get(t.name)
            if pos:
                item.setPos(pos[0], pos[1])
            else:
                col, row = i % 3, i // 3
                item.setPos(col * (WIDTH + 90), row * 230)
            self.scene.addItem(item)
            self.items[t.name] = item
        for r in self.ws.relationships():
            c, p = self.items.get(r.child), self.items.get(r.parent)
            if c and p:
                link = LinkItem(c, r.child_field, p, r.parent_field, r)
                self.scene.addItem(link)
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-60, -60, 60, 60))

    def save_positions(self):
        self.ws.save_layout({n: [i.pos().x(), i.pos().y()] for n, i in self.items.items()})
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-60, -60, 60, 60))

    def fit(self):
        if self.items:
            self.view.fitInView(self.scene.itemsBoundingRect().adjusted(-30, -30, 30, 30),
                                Qt.KeepAspectRatio)

    def showEvent(self, event):
        super().showEvent(event)
        if self.ws.is_open:
            self.rebuild()
            self.fit()

    def _menu(self, pos):
        item = self.view.itemAt(pos)
        if isinstance(item, LinkItem):
            menu = QMenu(self)
            menu.addAction(_("Remove this relationship"), lambda: self.remove_link(item))
            menu.exec(self.view.viewport().mapToGlobal(pos))

    def link_tables(self):
        if not self.ws.tables():
            QMessageBox.information(self, _("Link tables"), _("Create a table first."))
            return
        dialog = LinkDialog(self.ws, self)
        if dialog.exec() != QDialog.Accepted:
            return
        child = dialog.child.currentData()
        field = dialog.field.currentData()
        target = dialog.parent_key.currentData()
        if not field or not target:
            QMessageBox.information(self, _("Link tables"), _("The other table needs a key field."))
            return
        self._set_link(child.name, field, target[0], target[1], dialog.action.currentData())

    def remove_link(self, link: LinkItem):
        self._set_link(link.child.record.name, link.child_field, "", "", "NO ACTION")

    def _set_link(self, table: str, field: str, ref_table: str, ref_field: str, action: str):
        record = self.ws.table(table)
        design = design_of(record)
        fields = tuple(replace(f, ref_table=ref_table, ref_field=ref_field, on_delete=action)
                       if f.name == field else f for f in design.fields)
        try:
            self.ws.save_table(table, type(design)(design.name, fields))
        except ApplicationError as e:
            QMessageBox.warning(self, _("Link tables"), _(str(e)))

"""Reports: grouped, totalled and ready to print."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, QSettings, Qt
from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QMessageBox, QStackedWidget,
    QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ...application.errors import ApplicationError
from ...application.inputs import ReportDef
from ...application.workspace import Change, Source, Workspace
from ..i18n import _
from ..report_html import report_html
from .common import Card, Segmented, button, icon_button, label, primary_button
from .forms import pick_source
from .objects import Header, ObjectPage


def document_for(html: str, landscape: bool) -> QTextDocument:
    doc = QTextDocument()
    doc.setHtml(html)
    return doc


def write_pdf(path: str, html: str, landscape: bool):
    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageOrientation(QPageLayout.Landscape if landscape else QPageLayout.Portrait)
    writer.setPageMargins(QMarginsF(14, 14, 14, 14), QPageLayout.Millimeter)
    doc = document_for(html, landscape)
    doc.print_(writer)


class ReportDesigner(QWidget):
    def __init__(self, workspace: Workspace, parent=None):
        super().__init__(parent)
        self.ws = workspace
        self.report: ReportDef | None = None
        self.title = QLineEdit(objectName="titleEdit", placeholderText=_("Report title"))
        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setHeaderLabels([_("Show"), _("Column"), _("Add up")])
        self.tree.setColumnWidth(0, 70)
        self.tree.setColumnWidth(1, 220)
        self.group = QComboBox()
        self.sort = QComboBox()
        self.descending = QCheckBox(_("Largest first"))
        self.landscape = QCheckBox(_("Wide page (landscape)"))
        self.up = icon_button("chevron-up", _("Move up"))
        self.down = icon_button("chevron-down", _("Move down"))
        self.up.clicked.connect(lambda: self._move(-1))
        self.down.clicked.connect(lambda: self._move(1))
        options = QHBoxLayout()
        options.setSpacing(8)
        options.addWidget(label(_("Group by")))
        options.addWidget(self.group)
        options.addWidget(label(_("Sort by")))
        options.addWidget(self.sort)
        options.addWidget(self.descending)
        options.addStretch()
        options.addWidget(self.up)
        options.addWidget(self.down)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.title)
        layout.addLayout(options)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.landscape)

    def load(self, report: ReportDef):
        self.report = report
        self.title.setText(report.title)
        columns = self.ws.columns(Source(report.source_kind, report.source))
        names = [c.name for c in columns]
        types = {c.name: c.type for c in columns}
        for box, current in ((self.group, report.group_by), (self.sort, report.sort_by)):
            box.clear()
            box.addItem(_("(none)"), "")
            for n in names:
                box.addItem(n, n)
            box.setCurrentIndex(max(0, box.findData(current)))
        self.descending.setChecked(report.descending)
        self.landscape.setChecked(report.landscape)
        self.tree.clear()
        shown = [c for c in report.columns if c in names]
        for n in shown + [n for n in names if n not in shown]:
            item = QTreeWidgetItem(["", n, ""])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if n in shown else Qt.Unchecked)
            numeric = types[n] is not None and types[n].is_numeric
            if numeric:
                item.setCheckState(2, Qt.Checked if n in report.sum_columns else Qt.Unchecked)
            self.tree.addTopLevelItem(item)
            item.setData(1, Qt.UserRole, numeric)

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

    def result(self) -> ReportDef:
        r = self.report
        cols, sums = [], []
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.checkState(0) == Qt.Checked:
                cols.append(it.text(1))
                if it.data(1, Qt.UserRole) and it.checkState(2) == Qt.Checked:
                    sums.append(it.text(1))
        return ReportDef(r.source, r.source_kind, self.title.text().strip(), tuple(cols),
                         self.group.currentData() or "", self.sort.currentData() or "",
                         self.descending.isChecked(), tuple(sums), self.landscape.isChecked())


class ReportsPage(ObjectPage):
    def __init__(self, workspace: Workspace, parent=None):
        super().__init__(_("Reports"), _("Group, total and print your data."), _("New report"),
                         "report", _("Create a report from a table or a query."), parent)
        self.ws = workspace
        self.current: str | None = None
        self.preview = QTextBrowser(objectName="paper")
        self.preview.setOpenLinks(False)
        self.designer = ReportDesigner(workspace)
        card = Card(None, 14)
        self.header = Header()
        self.mode = Segmented([("preview", _("Preview")), ("design", _("Design"))])
        self.save_button = primary_button(_("Save design"), "check")
        self.pdf_button = button(_("Export PDF…"), "download")
        self.print_button = button(_("Print…"))
        self.delete_button = button(_("Delete"), "trash")
        self.delete_button.setObjectName("danger")
        for w in (self.mode, self.save_button, self.pdf_button, self.print_button, self.delete_button):
            self.header.add(w)
        self.views = QStackedWidget()
        self.views.addWidget(self.preview)
        self.views.addWidget(self.designer)
        card.add(self.header)
        card.add(self.views, 1)
        self.add_view(card)
        self.card = card
        self.html = ""
        self.items.chosen.connect(self.open_report)
        self.items.newRequested.connect(self.new_report)
        self.mode.changed.connect(self._mode)
        self.save_button.clicked.connect(self.save_design)
        self.pdf_button.clicked.connect(self.export_pdf)
        self.print_button.clicked.connect(self.print_report)
        self.delete_button.clicked.connect(self.delete)
        workspace.subscribe(self._changed)
        self.refresh()

    def refresh(self, select: str | None = None):
        if not self.ws.is_open:
            self.items.set_items([])
            return
        want = select or self.current
        self.items.set_items([(n, self.ws.report(n).source) for n in self.ws.reports()], want,
                             _("No reports yet."))

    def _changed(self, change):
        if change in (Change.OPENED, Change.CLOSED):
            self.current = None
            self.refresh()
        elif change is Change.SCHEMA and self.ws.is_open:
            self.refresh()
        elif change is Change.DATA and self.isVisible() and self.current \
                and self.mode.value() == "preview":
            self.render()

    def open_report(self, name: str):
        self.current = name or None
        if not name:
            self.stack.setCurrentWidget(self.placeholder)
            return
        self.header.title.setText(name)
        self.stack.setCurrentWidget(self.card)
        self.mode.set_value("preview")
        self._mode("preview")

    def render(self):
        report = self.ws.report(self.current)
        try:
            view = self.ws.build_report(report)
            columns = self.ws.columns(Source(report.source_kind, report.source))
            types = {c.name: c.type for c in columns}
            currencies = {c.name: c.currency for c in columns}
        except ApplicationError as e:
            self.preview.setPlainText(_(str(e)))
            self.html = ""
            return
        self.html = report_html(report.title or self.current, view, types, currencies)
        self.preview.setHtml(self.html)

    def _mode(self, mode):
        design = mode == "design"
        self.save_button.setVisible(design)
        self.pdf_button.setVisible(not design)
        self.print_button.setVisible(not design)
        if design:
            self.designer.load(self.ws.report(self.current))
        else:
            self.render()
        self.views.setCurrentWidget(self.designer if design else self.preview)

    def new_report(self):
        picked = pick_source(self.ws, self, _("New report"))
        if not picked:
            return
        name, source = picked
        n, k = name, 2
        while n in self.ws.reports():
            n, k = f"{name} {k}", k + 1
        try:
            self.ws.save_report(n, None, self.ws.default_report(source))
        except ApplicationError as e:
            QMessageBox.warning(self, _("Folio"), _(str(e)))
            return
        self.refresh(n)
        self.open_report(n)
        self.mode.set_value("design")
        self._mode("design")

    def save_design(self):
        try:
            self.ws.save_report(self.current, self.current, self.designer.result())
        except ApplicationError as e:
            QMessageBox.warning(self, _("Folio"), _(str(e)))
            return
        self.mode.set_value("preview")
        self._mode("preview")

    def _landscape(self) -> bool:
        return self.ws.report(self.current).landscape

    def export_pdf(self):
        if not self.html:
            return
        folder = QSettings().value("folder", "") or str(Path.home())
        path = QFileDialog.getSaveFileName(self, _("Export PDF"),
                                           str(Path(folder) / f"{self.current}.pdf"),
                                           "PDF (*.pdf)")[0]
        if path:
            write_pdf(path, self.html, self._landscape())

    def print_report(self):
        if not self.html:
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageOrientation(QPageLayout.Landscape if self._landscape() else QPageLayout.Portrait)
        if QPrintDialog(printer, self).exec() == QPrintDialog.Accepted:
            document_for(self.html, self._landscape()).print_(printer)

    def delete(self):
        if self.current and self.confirm_delete(_("Delete report"), self.current):
            self.ws.delete_report(self.current)
            self.current = None
            self.refresh()

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox,
    QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from .. import FILE_EXTENSION, HOMEPAGE, __version__
from ..application.errors import ApplicationError
from ..application.services import Services
from ..application.workspace import Change
from ..demo import build_library
from . import theme
from .fit import clamp_window
from .i18n import N_, _, plural
from .icons import APP_ICON
from .settings import SettingsDialog
from .updates_ui import UpdateChecker
from .views.forms import FormsPage
from .views.home import HomePage
from .views.queries import QueriesPage
from .views.relations import RelationsPage
from .views.reports import ReportsPage
from .views.tables import TablesPage

OPEN_TYPES = (".folio", ".db", ".sqlite", ".sqlite3")
ACCESS_TYPES = (".accdb", ".mdb")


class Sidebar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(206)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        brand_icon = QLabel()
        brand_icon.setPixmap(QIcon(str(APP_ICON)).pixmap(28, 28))
        brand = QHBoxLayout()
        brand.setContentsMargins(12, 4, 12, 0)
        brand.setSpacing(10)
        brand.addWidget(brand_icon)
        brand.addWidget(QLabel(_("Folio"), objectName="brand"))
        brand.addStretch()
        self.nav = QVBoxLayout()
        self.nav.setSpacing(2)
        self.footer = QVBoxLayout()
        self.footer.setSpacing(2)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 20, 12, 14)
        layout.setSpacing(6)
        layout.addLayout(brand)
        layout.addSpacing(18)
        layout.addLayout(self.nav)
        layout.addStretch()
        layout.addLayout(self.footer)

    def nav_button(self, icon_name: str, text: str, checkable: bool = True) -> QToolButton:
        button = QToolButton(objectName="nav", text=f"  {text}", checkable=checkable)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.setIconSize(QSize(18, 18))
        button.setCursor(Qt.PointingHandCursor)
        theme.set_icon(button, icon_name, "muted", "accent" if checkable else None)
        return button

    def add_page(self, icon_name: str, text: str, shortcut: str) -> QToolButton:
        button = self.nav_button(icon_name, text)
        button.setToolTip(f"{text}  ({shortcut})")
        self.group.addButton(button, len(self.group.buttons()))
        self.nav.addWidget(button)
        return button


class MainWindow(QMainWindow):
    HOME, TABLES, QUERIES, FORMS, REPORTS, RELATIONS = range(6)
    PAGES = [("home", N_("Home")), ("table", N_("Tables")), ("query", N_("Queries")),
             ("form", N_("Forms")), ("report", N_("Reports")), ("relations", N_("Relationships"))]

    def __init__(self, services: Services):
        super().__init__()
        self.services = services
        self.ws = services.workspace
        clamp_window(self, 1320, 840, 1000, 640)
        self.setAcceptDrops(True)

        self.home = HomePage()
        self.tables = TablesPage(self.ws)
        self.queries = QueriesPage(self.ws)
        self.forms = FormsPage(self.ws)
        self.reports = ReportsPage(self.ws)
        self.relations = RelationsPage(self.ws)
        self.sidebar = Sidebar()
        self.stack = QStackedWidget()
        pages = (self.home, self.tables, self.queries, self.forms, self.reports, self.relations)
        for i, (page, (icon, text)) in enumerate(zip(pages, self.PAGES)):
            self.stack.addWidget(page)
            self.sidebar.add_page(icon, _(text), f"Ctrl+{i + 1}")
        self.sidebar.group.idClicked.connect(self.show_page)
        more = self.sidebar.nav_button("more", _("More"), checkable=False)
        more.setPopupMode(QToolButton.InstantPopup)
        more.setMenu(self._more_menu())
        self.sidebar.footer.addWidget(more)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.home.newRequested.connect(self.new_database)
        self.home.openRequested.connect(lambda path: self.open_file(path or None))
        self.home.sampleRequested.connect(self.open_sample)
        self.home.accessRequested.connect(self.open_access)
        self.ws.subscribe(self._changed)
        self.updater = UpdateChecker(self.services, self)
        self._shortcuts()

        geometry = QSettings().value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        self.home.set_recent(self.ws.recent())
        self._changed(Change.CLOSED)
        self.show_page(self.HOME)

    # ---- pages -----------------------------------------------------------------------
    def show_page(self, index: int):
        if index != self.HOME and not self.ws.is_open:
            index = self.HOME
        self.stack.setCurrentIndex(index)
        self.sidebar.group.button(index).setChecked(True)

    def _changed(self, change):
        if change in (Change.OPENED, Change.CLOSED):
            for i in range(1, len(self.PAGES)):
                self.sidebar.group.button(i).setEnabled(self.ws.is_open)
            self.setWindowTitle(f"{self.ws.name} — Folio" if self.ws.is_open else "Folio")
            self.home.set_recent(self.ws.recent())
            if change is Change.OPENED:
                self.show_page(self.TABLES)
            else:
                self.show_page(self.HOME)

    # ---- files -----------------------------------------------------------------------
    def _folder(self) -> str:
        folder = QSettings().value("folder", "")
        return folder if folder and Path(folder).is_dir() else str(Path.home())

    def _remember_folder(self, path: str):
        QSettings().setValue("folder", str(Path(path).parent))

    def _guard(self, action) -> bool:
        try:
            action()
            return True
        except ApplicationError as e:
            QMessageBox.warning(self, "Folio", _(str(e)))
            return False

    def new_database(self):
        path, chosen = QFileDialog.getSaveFileName(
            self, _("New database"), str(Path(self._folder()) / f"database{FILE_EXTENSION}"),
            _("Folio databases") + f" (*{FILE_EXTENSION});;" + _("Access databases") + " (*.accdb)")
        if not path:
            return
        if not Path(path).suffix:
            path += ".accdb" if "accdb" in chosen else FILE_EXTENSION
        self._remember_folder(path)
        if self._guard(lambda: self.ws.create(path)):
            self.tables.new_table()

    def open_file(self, path: str | None = None):
        if not path:
            patterns = " ".join(f"*{e}" for e in OPEN_TYPES + ACCESS_TYPES)
            path, _filter = QFileDialog.getOpenFileName(
                self, _("Open"), self._folder(),
                _("Databases") + f" ({patterns});;" + _("All files") + " (*)")
        if not path:
            return
        self._remember_folder(path)
        if not self._guard(lambda: self.ws.open(path)):
            self.ws.forget(path)
            self.home.set_recent(self.ws.recent())

    def open_access(self):
        """Open an Access file right where it is: no conversion, changes go into the file."""
        path, _filter = QFileDialog.getOpenFileName(
            self, _("Open an Access file"), self._folder(),
            _("Access databases") + " (*.accdb *.mdb)")
        if path:
            self.open_file(path)

    def open_sample(self):
        target = Path(tempfile.gettempdir()) / "folio-school-library.folio"
        target.unlink(missing_ok=True)
        if self._guard(lambda: self.ws.create(str(target))):
            self._guard(lambda: build_library(self.ws))
            self.tables.refresh("Books")
            self.queries.refresh()
            self.forms.refresh()
            self.reports.refresh()

    def import_access(self, source: str | None = None):
        """Convert an Access file (.accdb / .mdb) into a new Folio database and open it."""
        if not source:
            source, _filter = QFileDialog.getOpenFileName(
                self, _("Convert an Access file to Folio"), self._folder(),
                _("Access databases") + " (*.accdb *.mdb)")
        if not source:
            return
        suggestion = Path(source).with_suffix(FILE_EXTENSION)
        target, _filter = QFileDialog.getSaveFileName(
            self, _("Save the converted database as"), str(suggestion),
            _("Folio databases") + f" (*{FILE_EXTENSION})")
        if not target:
            return
        if not Path(target).suffix:
            target += FILE_EXTENSION
        report = []
        if not self._guard(lambda: self.ws.create(target)):
            return
        if not self._guard(lambda: report.append(self.ws.import_access(source))):
            self.ws.close()
            Path(target).unlink(missing_ok=True)
            return
        self.tables.refresh()
        done = report[0]
        text = _("{tables} brought in, {rows} in all.").format(
            tables=plural(len(done.tables), "table"),
            rows=plural(sum(r.rows for r in done.tables), "row"))
        problems = sum(r.problems for r in done.tables)
        if problems:
            text += " " + _("{problems} values didn't fit and were left empty.").format(problems=problems)
        if done.links_lost:
            text += " " + _("{links} relationships couldn't be kept.").format(links=done.links_lost)
        if done.skipped_columns:
            text += " " + _("{columns} columns (pictures, attachments) were left out.").format(
                columns=done.skipped_columns)
        QMessageBox.information(self, _("Convert an Access file to Folio"), text)

    def export_access(self):
        """Create an Access file (.accdb) from the open database."""
        if not self.ws.is_open:
            return
        if self.ws.is_access:
            QMessageBox.information(self, _("Export to Access"),
                                    _("This already is an Access file."))
            return
        suggestion = str(Path(self._folder()) / f"{self.ws.name}.accdb")
        target, _filter = QFileDialog.getSaveFileName(
            self, _("Export to Access"), suggestion, _("Access databases") + " (*.accdb *.mdb)")
        if not target:
            return
        if not Path(target).suffix:
            target += ".accdb"
        self._remember_folder(target)
        report = []
        if not self._guard(lambda: report.append(self.ws.export_access(target))):
            return
        done = report[0]
        QMessageBox.information(
            self, _("Export to Access"),
            _("{tables} and {rows} saved to {file}.").format(
                tables=plural(done.tables, "table"), rows=plural(done.rows, "row"),
                file=Path(target).name) + " " +
            _("Saved queries, forms and reports stay in the Folio file: Access can't hold them."))

    # ---- menus and shortcuts -----------------------------------------------------------
    def _shortcut(self, keys, slot):
        action = QAction(self)
        action.setShortcut(QKeySequence(keys))
        action.setShortcutContext(Qt.ApplicationShortcut)
        action.triggered.connect(slot)
        self.addAction(action)

    def _shortcuts(self):
        for i in range(len(self.PAGES)):
            self._shortcut(f"Ctrl+{i + 1}", lambda _c=False, i=i: self.show_page(i))
        self._shortcut(QKeySequence.New, self.new_database)
        self._shortcut(QKeySequence.Open, lambda: self.open_file())
        self._shortcut("Ctrl+,", self.open_settings)
        self._shortcut(QKeySequence.Quit, self.close)
        self._shortcut("Ctrl+Q", self.close)

    def _more_menu(self) -> QMenu:
        menu = QMenu(self)
        entries = [
            (_("New database…"), "Ctrl+N", self.new_database),
            (_("Open…"), "Ctrl+O", lambda: self.open_file()),
            (_("Convert an Access file to Folio…"), None, lambda: self.import_access()),
            (_("Export to Access…"), None, self.export_access),
            (_("Close the database"), None, self.ws.close),
            (_("Compact the database"), None, lambda: self._guard(self.ws.compact)),
            None,
            (_("Settings…"), "Ctrl+,", self.open_settings),
            (_("Check for updates…"), None, lambda: self.updater.check_now()),
            (_("About Folio"), None, self.about),
            None,
            (_("Quit Folio"), "Ctrl+Q", self.close),
        ]
        for entry in entries:
            if entry is None:
                menu.addSeparator()
                continue
            text, keys, slot = entry
            action = menu.addAction(text, slot)
            if keys:
                action.setShortcut(QKeySequence(keys))
                action.setShortcutVisibleInContextMenu(True)
                action.setShortcutContext(Qt.WidgetShortcut)
        return menu

    def open_settings(self):
        SettingsDialog(self.services, self.updater, self).exec()

    def about(self):
        QMessageBox.about(
            self, _("About Folio"),
            f"<h3>Folio {__version__}</h3>"
            f"<p>{_('Tables, queries, forms and reports, in one file you can keep.')}</p>"
            f"<p><a href='{HOMEPAGE}'>{HOMEPAGE}</a></p>"
            f"<p>{_('Free software under the GNU General Public License, version 3 or later.')}</p>")

    # ---- window ----------------------------------------------------------------------
    def dragEnterEvent(self, event):
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                if Path(path).suffix.lower() in (".csv", ".tsv") and self.ws.is_open:
                    self.show_page(self.TABLES)
                    self.tables.import_file(path)
                else:
                    self.open_file(path)
                break

    def closeEvent(self, event):
        QSettings().setValue("window/geometry", self.saveGeometry())
        self.ws.close()
        super().closeEvent(event)

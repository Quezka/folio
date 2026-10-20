import os
from datetime import datetime

import pytest

os.environ.setdefault("QT_SCALE_FACTOR", "1")  # tests measure pixels: no automatic scaling

from folio.application.ports import AccessTable
from folio.application.services import Services
from folio.application.updates import UpdateService
from folio.application.workspace import Workspace
from folio.infrastructure.csv_files import CsvFilesAdapter
from folio.infrastructure.settings import MemorySettings
from folio.infrastructure.access_native import DatabaseRouter

from .fakes import FakeAccess, FakeInstaller, FakeReleases


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 20, 10, 0)

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def releases():
    return FakeReleases()


@pytest.fixture
def installer():
    return FakeInstaller()


@pytest.fixture
def access():
    return FakeAccess()


@pytest.fixture
def ws(tmp_path, access):
    """A workspace with a real (temporary) database file open."""
    workspace = Workspace(DatabaseRouter(), CsvFilesAdapter(), access, MemorySettings())
    workspace.create(str(tmp_path / "test.folio"))
    yield workspace
    workspace.close()


@pytest.fixture
def services(releases, installer, clock, tmp_path, access):
    workspace = Workspace(DatabaseRouter(), CsvFilesAdapter(), access, MemorySettings())
    service = Services(workspace, UpdateService(releases, installer, MemorySettings(), "0.2.0", clock))
    yield service
    workspace.close()


@pytest.fixture(scope="session", autouse=True)
def empty_clipboard():
    """Qt's headless test platform crashes at exit when the clipboard still holds data a
    test copied (real desktops don't), so empty it before the tests end."""
    yield
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is not None:
        app.clipboard().clear()


@pytest.fixture(autouse=True)
def full_hd_screen(monkeypatch):
    """The headless test screen is tiny; windows are clamped to the screen, so pretend it is
    a normal one (the clamp itself is tested in test_uiscale)."""
    try:
        from PySide6.QtCore import QRect
        from folio.presentation import fit
    except ImportError:
        return
    monkeypatch.setattr(fit, "available", lambda widget=None: QRect(0, 0, 1920, 1040))

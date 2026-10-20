"""The only place that knows which adapters implement which ports."""
from __future__ import annotations

from . import HOMEPAGE, __version__
from .application.ports import (AccessFiles, CsvFiles, DatabaseGateway, KeyValueStore,
                                ReleaseFeed, UpdateInstaller)
from .application.services import Services
from .application.updates import UpdateService
from .application.workspace import Workspace
from .infrastructure.access_files import AccessFilesAdapter
from .infrastructure.csv_files import CsvFilesAdapter
from .infrastructure.settings import JsonSettings
from .infrastructure.sqlite import SqliteDatabase
from .infrastructure.updates import GitHubReleaseFeed, platform_installer


def build_services(db: DatabaseGateway | None = None, csv: CsvFiles | None = None,
                   access: AccessFiles | None = None, settings: KeyValueStore | None = None,
                   releases: ReleaseFeed | None = None,
                   installer: UpdateInstaller | None = None) -> Services:
    settings = settings or JsonSettings()
    return Services(
        workspace=Workspace(db or SqliteDatabase(), csv or CsvFilesAdapter(),
                            access or AccessFilesAdapter(), settings),
        updates=UpdateService(
            releases or GitHubReleaseFeed(HOMEPAGE.removeprefix("https://github.com/"),
                                          __version__),
            installer or platform_installer(), settings, __version__),
    )

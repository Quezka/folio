"""Starts the Qt event loop around an already-wired set of services."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication
from quezka_ui.app import create_application as _create

from .. import APP_ID, APP_NAME
from ..application.services import Services

ICON = Path(__file__).resolve().parent.parent / "assets" / "icon.svg"


def create_application(argv: list[str]) -> QApplication:
    return _create(argv, name=APP_NAME, app_id=APP_ID, icon=ICON, locale_package="folio.presentation.locales")


def run(services: Services, argv: list[str], file: Path | None = None,
        demo: bool = False) -> int:
    from .main_window import MainWindow

    app = create_application(argv)
    window = MainWindow(services)
    window.show()
    if file is not None:
        window.open_file(str(file))
    elif demo:
        window.open_sample()
    return app.exec()

"""Everything the UI can ask for, in one place (built by `bootstrap`)."""
from __future__ import annotations

from dataclasses import dataclass

from .updates import AvailableUpdate, UpdateService
from .workspace import Workspace


@dataclass
class Services:
    workspace: Workspace
    updates: UpdateService


__all__ = ["AvailableUpdate", "Services"]

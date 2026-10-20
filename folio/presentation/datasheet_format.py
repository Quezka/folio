"""How a stored value is written for people to read."""
from __future__ import annotations

from ..application.types import FieldType
from .i18n import _


def format_cell(value, ftype: FieldType | None) -> str:
    if value is None:
        return ""
    if ftype is FieldType.YES_NO or isinstance(value, bool):
        return _("Yes") if value else _("No")
    if isinstance(value, float):
        return f"{value:.0f}" if value == int(value) and abs(value) < 1e15 else f"{value:g}" \
            if abs(value) < 1e15 else repr(value)
    if isinstance(value, bytes):
        return _("(binary data)")
    return str(value)

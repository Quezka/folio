"""How a stored value is written for people to read (and typed back)."""
from __future__ import annotations

from PySide6.QtCore import QDate, QDateTime, QLocale

from ..application.types import FieldType, currency_symbol
from .i18n import _


def _day_first() -> str | None:
    """The locale's short date format with a 4-digit year, if it starts with the day."""
    form = QLocale().dateFormat(QLocale.ShortFormat)
    if not form.lower().startswith("d"):
        return None  # month-first locales stay with the unambiguous 2026-10-20
    return form.replace("yy", "yyyy") if "yyyy" not in form else form


def format_date(iso: str) -> str:
    form = _day_first()
    date = QDate.fromString(iso[:10], "yyyy-MM-dd")
    return date.toString(form) if form and date.isValid() else iso[:10]


def format_datetime(iso: str) -> str:
    stamp = QDateTime.fromString(iso[:19].replace("T", " "), "yyyy-MM-dd HH:mm:ss")
    if not stamp.isValid():
        return iso
    time = stamp.time().toString("HH:mm:ss" if stamp.time().second() else "HH:mm")
    return f"{format_date(iso)} {time}"


def format_money(value: float, code: str) -> str:
    digits = 0 if code == "JPY" else 2
    return QLocale().toCurrencyString(float(value), currency_symbol(code or "EUR"), digits)


def format_cell(value, ftype: FieldType | None, currency: str = "") -> str:
    if value is None:
        return ""
    if ftype is FieldType.YES_NO or isinstance(value, bool):
        return _("Yes") if value else _("No")
    if ftype is FieldType.CURRENCY and isinstance(value, (int, float)):
        return format_money(value, currency)
    if ftype is FieldType.DATE and isinstance(value, str):
        return format_date(value)
    if ftype is FieldType.DATETIME and isinstance(value, str):
        return format_datetime(value)
    if isinstance(value, float):
        return f"{value:.0f}" if value == int(value) and abs(value) < 1e15 else \
            (f"{value:g}" if abs(value) < 1e15 else repr(value))
    if isinstance(value, bytes):
        return _("(binary data)")
    return str(value)


def edit_text(value, ftype: FieldType | None) -> str:
    """The text of a value while it is being edited (what the field accepts back)."""
    if value is None:
        return ""
    if ftype in (FieldType.DATE, FieldType.DATETIME) and isinstance(value, str):
        return format_date(value) if ftype is FieldType.DATE else format_datetime(value)
    if isinstance(value, float):
        return f"{value:.0f}" if value == int(value) and abs(value) < 1e15 else repr(value)
    return str(value)

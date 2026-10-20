"""Turning what a person typed into a value that fits a field's type, and back."""
from __future__ import annotations

import re
from datetime import date, datetime

from .schema import FieldType


class InvalidValueError(ValueError):
    """The text doesn't fit the field (the message is shown to the user)."""


TRUE = {"1", "true", "yes", "y", "si", "sì", "да", "vero", "on", "x", "✓"}
FALSE = {"0", "false", "no", "n", "нет", "falso", "off"}
_DATE_FORMS = ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%Y/%m/%d")
_TIME_FORMS = ("%H:%M:%S", "%H:%M")


def parse_date(text: str) -> date:
    text = text.strip()
    for form in _DATE_FORMS:
        try:
            return datetime.strptime(text, form).date()
        except ValueError:
            pass
    raise InvalidValueError("That isn't a date. Write it like 2026-10-20.")


def parse_datetime(text: str) -> datetime:
    text = text.strip().replace("T", " ")
    day, _, time = text.partition(" ")
    parsed = parse_date(day)
    if not time.strip():
        return datetime(parsed.year, parsed.month, parsed.day)
    for form in _TIME_FORMS:
        try:
            t = datetime.strptime(time.strip(), form).time()
            return datetime.combine(parsed, t)
        except ValueError:
            pass
    raise InvalidValueError("That isn't a date and time. Write it like 2026-10-20 14:30.")


def coerce(text, ftype: FieldType):
    """The value to store for `text` (None for empty). Raises InvalidValueError."""
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    if ftype in (FieldType.TEXT, FieldType.LONG_TEXT):
        return text if text != "" else None
    text = text.strip()
    if text == "":
        return None
    if ftype is FieldType.INTEGER:
        try:
            return int(text)
        except ValueError:
            try:
                number = float(text.replace(",", "."))
            except ValueError:
                raise InvalidValueError("That isn't a whole number.") from None
            if number != int(number):
                raise InvalidValueError("That isn't a whole number.")
            return int(number)
    if ftype is FieldType.NUMBER:
        cleaned = text.replace(",", ".") if "." not in text else text.replace(",", "")
        try:
            return float(cleaned)
        except ValueError:
            raise InvalidValueError("That isn't a number.") from None
    if ftype is FieldType.YES_NO:
        low = text.lower()
        if low in TRUE:
            return 1
        if low in FALSE:
            return 0
        raise InvalidValueError("Write yes or no.")
    if ftype is FieldType.DATE:
        return parse_date(text).isoformat()
    if ftype is FieldType.DATETIME:
        return parse_datetime(text).strftime("%Y-%m-%d %H:%M:%S")
    raise InvalidValueError("That value doesn't fit.")  # pragma: no cover


def guess_type(samples: list[str]) -> FieldType:
    """The narrowest type every non-empty sample fits (used when importing a CSV)."""
    values = [s.strip() for s in samples if s is not None and s.strip() != ""]
    if not values:
        return FieldType.TEXT

    def fits(ftype: FieldType) -> bool:
        try:
            for v in values:
                coerce(v, ftype)
        except InvalidValueError:
            return False
        return True

    if all(v.lower() in ("yes", "no", "true", "false") for v in values):
        return FieldType.YES_NO
    if any(re.fullmatch(r"[+-]?0\d+", v) for v in values):
        return FieldType.TEXT  # codes like 007 or 00100 keep their zeros
    if all(re.fullmatch(r"[+-]?\d+", v) for v in values) and fits(FieldType.INTEGER):
        return FieldType.INTEGER
    if all(re.fullmatch(r"[+-]?\d+([.,]\d+)?", v) for v in values) and fits(FieldType.NUMBER):
        return FieldType.NUMBER
    if all(re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{1,2}[/.]\d{1,2}[/.]\d{4}", v) for v in values) \
            and fits(FieldType.DATE):
        return FieldType.DATE
    if all(re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2}(:\d{2})?", v) for v in values) \
            and fits(FieldType.DATETIME):
        return FieldType.DATETIME
    if any(len(v) > 200 or "\n" in v for v in values):
        return FieldType.LONG_TEXT
    return FieldType.TEXT

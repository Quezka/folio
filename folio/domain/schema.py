"""Tables, fields and relationships: what a database looks like, free of any engine."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum


class SchemaError(Exception):
    """A table design that can't work (the message is shown to the user)."""


class FieldType(Enum):
    TEXT = "text"
    LONG_TEXT = "longtext"
    INTEGER = "integer"
    NUMBER = "number"
    CURRENCY = "currency"
    YES_NO = "yesno"
    DATE = "date"
    DATETIME = "datetime"

    @property
    def declared(self) -> str:
        """The column type written in CREATE TABLE (SQLite keeps unknown names as given)."""
        return _DECLARED[self]

    @property
    def is_numeric(self) -> bool:
        return self in (FieldType.INTEGER, FieldType.NUMBER, FieldType.CURRENCY)

    @staticmethod
    def from_declared(declared: str) -> "FieldType":
        d = (declared or "").upper()
        if "CURRENCY" in d or "MONEY" in d:
            return FieldType.CURRENCY
        if d == "LONGTEXT" or "CLOB" in d:
            return FieldType.LONG_TEXT
        if "BOOL" in d:
            return FieldType.YES_NO
        if "DATETIME" in d or "TIMESTAMP" in d:
            return FieldType.DATETIME
        if "DATE" in d:
            return FieldType.DATE
        if "INT" in d:
            return FieldType.INTEGER
        if any(w in d for w in ("REAL", "FLOA", "DOUB", "NUM", "DEC")):
            return FieldType.NUMBER
        return FieldType.TEXT


_DECLARED = {
    FieldType.TEXT: "TEXT", FieldType.LONG_TEXT: "LONGTEXT", FieldType.INTEGER: "INTEGER",
    FieldType.NUMBER: "REAL", FieldType.CURRENCY: "CURRENCY", FieldType.YES_NO: "BOOLEAN", FieldType.DATE: "DATE",
    FieldType.DATETIME: "DATETIME",
}

ON_DELETE = ("NO ACTION", "CASCADE", "SET NULL")

DEFAULT_CURRENCY = "EUR"
CURRENCIES = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF", "RUB": "₽", "JPY": "¥",
              "PLN": "zł", "CZK": "Kč", "SEK": "kr", "NOK": "kr", "DKK": "kr", "CAD": "$",
              "AUD": "$", "CNY": "¥", "INR": "₹", "TRY": "₺", "UAH": "₴"}
SYMBOL_CODES = {"€": "EUR", "$": "USD", "£": "GBP", "₽": "RUB", "¥": "JPY", "₹": "INR",
                "₺": "TRY", "₴": "UAH", "zł": "PLN", "Kč": "CZK"}


def currency_symbol(code: str) -> str:
    return CURRENCIES.get(code, code)


def declared_type(f: "Field") -> str:
    """The column type written in CREATE TABLE: money carries its currency, CURRENCY_EUR
    (SQLite only allows numbers in parentheses; an unknown name keeps NUMERIC affinity)."""
    if f.type is FieldType.CURRENCY:
        return f"CURRENCY_{(f.currency or DEFAULT_CURRENCY).upper()}"
    return f.type.declared


def parse_declared(declared: str) -> tuple[FieldType, str]:
    """A declared column type back into a field type and (for money) its currency code."""
    ftype = FieldType.from_declared(declared)
    if ftype is not FieldType.CURRENCY:
        return ftype, ""
    inside = (declared or "").upper().partition("CURRENCY_")[2].strip()
    return ftype, inside if inside.isalpha() and len(inside) == 3 else DEFAULT_CURRENCY


def quote(name: str) -> str:
    """An identifier safe to put in SQL."""
    return '"' + name.replace('"', '""') + '"'


def literal(value) -> str:
    """A value written as an SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


@dataclass(frozen=True)
class Field:
    name: str
    type: FieldType = FieldType.TEXT
    primary_key: bool = False
    autonumber: bool = False  # a whole number that counts up by itself (implies primary key)
    required: bool = False
    unique: bool = False
    default: str | None = None  # as the user typed it; "today" / "now" are understood
    currency: str = ""  # for money fields: the code, e.g. "EUR"


@dataclass(frozen=True)
class ForeignKey:
    field: str
    ref_table: str
    ref_field: str
    on_delete: str = "NO ACTION"


@dataclass(frozen=True)
class Table:
    name: str
    fields: tuple[Field, ...] = ()
    foreign_keys: tuple[ForeignKey, ...] = ()
    locked: bool = False  # uses features the designer can't keep (checks, composite keys…)

    def field(self, name: str) -> Field | None:
        return next((f for f in self.fields if f.name == name), None)

    @property
    def primary_key(self) -> tuple[Field, ...]:
        return tuple(f for f in self.fields if f.primary_key)

    def foreign_key(self, field_name: str) -> ForeignKey | None:
        return next((k for k in self.foreign_keys if k.field == field_name), None)

    def with_foreign_key(self, key: ForeignKey) -> "Table":
        rest = tuple(k for k in self.foreign_keys if k.field != key.field)
        return replace(self, foreign_keys=rest + (key,))

    def label_field(self) -> str | None:
        """The field that best names a row in a drop-down: the first text field."""
        for f in self.fields:
            if f.type in (FieldType.TEXT, FieldType.LONG_TEXT) and not f.primary_key:
                return f.name
        return next((f.name for f in self.fields if not f.primary_key), None)


def default_clause(f: Field) -> str:
    """` DEFAULT …` for a field, or ''. Raises SchemaError if the default doesn't fit."""
    text = (f.default or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if f.type is FieldType.DATE and lowered in ("today", "date()"):
        return " DEFAULT (date('now','localtime'))"
    if f.type is FieldType.DATETIME and lowered in ("now", "today"):
        return " DEFAULT (datetime('now','localtime'))"
    from .values import InvalidValueError, coerce  # local: values imports this module
    try:
        value = coerce(text, f.type)
    except InvalidValueError:
        raise SchemaError("A default value doesn't fit its field's type.") from None
    return f" DEFAULT {literal(value)}"


def validate_table(table: Table) -> None:
    if not table.name.strip():
        raise SchemaError("A table needs a name.")
    if table.name.lower().startswith(("sqlite_", "_folio")):
        raise SchemaError("Table names can't start with sqlite_ or _folio.")
    if not table.fields:
        raise SchemaError("A table needs at least one field.")
    seen = set()
    for f in table.fields:
        if not f.name.strip():
            raise SchemaError("Every field needs a name.")
        if f.name.lower() in seen:
            raise SchemaError("Two fields have the same name.")
        seen.add(f.name.lower())
        if f.autonumber and f.type is not FieldType.INTEGER:
            raise SchemaError("Only a whole-number field can count up by itself.")
        default_clause(f)
    if sum(f.autonumber for f in table.fields) > 1:
        raise SchemaError("Only one field can count up by itself.")
    for f in table.fields:
        if f.autonumber and (len(table.primary_key) != 1 or not f.primary_key):
            raise SchemaError("A field that counts up by itself must be the only key.")
    for key in table.foreign_keys:
        if key.field not in seen and table.field(key.field) is None:
            raise SchemaError("A relationship uses a field that doesn't exist.")


def create_table_sql(table: Table, name: str | None = None) -> str:
    """CREATE TABLE for a design (raises SchemaError if it isn't valid)."""
    validate_table(table)
    pk = table.primary_key
    lines = []
    for f in table.fields:
        parts = [quote(f.name), declared_type(f)]
        if f.autonumber:
            parts.append("PRIMARY KEY AUTOINCREMENT")
        elif f.primary_key and len(pk) == 1:
            parts.append("PRIMARY KEY")
        if f.required and not f.primary_key:
            parts.append("NOT NULL")
        if f.unique and not f.primary_key:
            parts.append("UNIQUE")
        lines.append(" ".join(parts) + default_clause(f))
    if len(pk) > 1:
        lines.append("PRIMARY KEY (" + ", ".join(quote(f.name) for f in pk) + ")")
    for key in table.foreign_keys:
        action = key.on_delete if key.on_delete in ON_DELETE else "NO ACTION"
        lines.append(f"FOREIGN KEY ({quote(key.field)}) REFERENCES {quote(key.ref_table)} "
                     f"({quote(key.ref_field)}) ON DELETE {action}")
    return f"CREATE TABLE {quote(name or table.name)} (\n  " + ",\n  ".join(lines) + "\n)"


@dataclass(frozen=True)
class Relationship:
    """One table's field pointing at another table's key (one parent, many children)."""
    child: str
    child_field: str
    parent: str
    parent_field: str
    on_delete: str = "NO ACTION"


def relationships(tables: list[Table]) -> list[Relationship]:
    return [Relationship(t.name, k.field, k.ref_table, k.ref_field, k.on_delete)
            for t in tables for k in t.foreign_keys]

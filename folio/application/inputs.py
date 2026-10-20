"""What the UI sends to the use cases. Plain, immutable values (some are the domain's own
data classes, re-exported so the UI never imports the domain itself)."""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.schema import FieldType


@dataclass(frozen=True)
class FieldDesign:
    """One row of the table designer."""
    name: str
    type: FieldType = FieldType.TEXT
    primary_key: bool = False
    autonumber: bool = False
    required: bool = False
    unique: bool = False
    default: str = ""
    currency: str = ""  # for money fields: "EUR", "USD"…
    original_name: str | None = None  # the field's name before this edit; None: a new field
    ref_table: str = ""  # "Links to": the table this field points at ("" for none)
    ref_field: str = ""
    on_delete: str = "NO ACTION"


@dataclass(frozen=True)
class TableDesign:
    name: str
    fields: tuple[FieldDesign, ...]


@dataclass(frozen=True)
class ImportField:
    name: str
    type: FieldType
    column: int  # index of the CSV column that feeds it
    currency: str = ""


@dataclass(frozen=True)
class ImportSpec:
    path: str
    table: str
    fields: tuple[ImportField, ...]
    has_header: bool = True
    add_key: bool = True  # also add an "id" field that counts up by itself
    append: bool = False  # add to an existing table instead of creating one


# ---- queries, forms and reports (the application's own shapes of the domain's designs) ------

@dataclass(frozen=True)
class Join:
    left_table: str
    left_field: str
    right_table: str
    right_field: str
    kind: str = "inner"  # "left" keeps left rows that have no match


@dataclass(frozen=True)
class QueryColumn:
    table: str
    field: str
    show: bool = True
    sort: str = ""
    total: str = ""
    criteria: str = ""
    or_criteria: str = ""
    alias: str = ""


@dataclass(frozen=True)
class QueryDesign:
    tables: tuple[str, ...] = ()
    joins: tuple[Join, ...] = ()
    columns: tuple[QueryColumn, ...] = ()
    distinct: bool = False


@dataclass(frozen=True)
class FormField:
    name: str
    label: str = ""
    read_only: bool = False


@dataclass(frozen=True)
class FormDef:
    source: str
    source_kind: str = "table"  # "table" | "query"
    title: str = ""
    fields: tuple[FormField, ...] = ()
    columns: int = 1


@dataclass(frozen=True)
class ReportDef:
    source: str
    source_kind: str = "table"
    title: str = ""
    columns: tuple[str, ...] = ()
    group_by: str = ""
    sort_by: str = ""
    descending: bool = False
    sum_columns: tuple[str, ...] = ()
    landscape: bool = False

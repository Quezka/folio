"""What the use cases hand back to the UI: read-only values."""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.schema import FieldType
from .inputs import QueryDesign


@dataclass(frozen=True)
class FieldRecord:
    name: str
    type: FieldType
    primary_key: bool
    autonumber: bool
    required: bool
    unique: bool
    default: str
    ref_table: str = ""
    ref_field: str = ""
    on_delete: str = "NO ACTION"


@dataclass(frozen=True)
class TableRecord:
    name: str
    fields: tuple[FieldRecord, ...]
    row_count: int
    locked: bool = False  # the designer can't change it without losing something

    def field(self, name: str) -> FieldRecord | None:
        return next((f for f in self.fields if f.name == name), None)


@dataclass(frozen=True)
class ColumnRecord:
    name: str
    type: FieldType | None  # None: a query column whose type isn't known
    ref_table: str = ""  # the column shows a lookup
    editable: bool = True
    required: bool = False


@dataclass(frozen=True)
class RowRecord:
    key: int | None  # the row's id in its table; None for query results
    values: tuple


@dataclass(frozen=True)
class PageRecord:
    columns: tuple[ColumnRecord, ...]
    rows: tuple[RowRecord, ...]
    total: int  # how many rows match in all (not just on this page)


@dataclass(frozen=True)
class QueryRecord:
    name: str
    sql: str
    design: QueryDesign | None  # None: written as SQL


@dataclass(frozen=True)
class LookupOption:
    key: object
    label: str


@dataclass(frozen=True)
class CsvPreview:
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]  # the first few data rows
    types: tuple[FieldType, ...]  # guessed per column
    total_rows: int


@dataclass(frozen=True)
class RelationshipRecord:
    child: str
    child_field: str
    parent: str
    parent_field: str
    on_delete: str = "NO ACTION"


@dataclass(frozen=True)
class ReportGroup:
    key: object
    rows: tuple[tuple, ...]
    sums: tuple  # one entry per column; a number for summed columns, else None


@dataclass(frozen=True)
class ReportView:
    columns: tuple[str, ...]
    group_by: str
    groups: tuple[ReportGroup, ...]
    totals: tuple
    row_count: int

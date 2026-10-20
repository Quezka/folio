"""Forms and reports: how saved rows are laid out for reading and printing."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FormField:
    name: str
    label: str = ""
    read_only: bool = False


@dataclass(frozen=True)
class FormDef:
    source: str  # a table or a saved query
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


def form_to_dict(f: FormDef) -> dict:
    return {"source": f.source, "source_kind": f.source_kind, "title": f.title,
            "columns": f.columns, "fields": [vars(x) | {} for x in f.fields]}


def form_from_dict(d: dict) -> FormDef:
    return FormDef(d["source"], d.get("source_kind", "table"), d.get("title", ""),
                   tuple(FormField(**x) for x in d.get("fields", ())), int(d.get("columns", 1)))


def report_to_dict(r: ReportDef) -> dict:
    return {"source": r.source, "source_kind": r.source_kind, "title": r.title,
            "columns": list(r.columns), "group_by": r.group_by, "sort_by": r.sort_by,
            "descending": r.descending, "sum_columns": list(r.sum_columns),
            "landscape": r.landscape}


def report_from_dict(d: dict) -> ReportDef:
    return ReportDef(d["source"], d.get("source_kind", "table"), d.get("title", ""),
                     tuple(d.get("columns", ())), d.get("group_by", ""), d.get("sort_by", ""),
                     bool(d.get("descending", False)), tuple(d.get("sum_columns", ())),
                     bool(d.get("landscape", False)))


# ---- building a report from rows -----------------------------------------------------

@dataclass(frozen=True)
class ReportGroup:
    key: object
    rows: tuple[tuple, ...]
    sums: tuple  # one entry per column; a number for summed columns, else None


@dataclass(frozen=True)
class ReportData:
    columns: tuple[str, ...]
    group_by: str
    groups: tuple[ReportGroup, ...]
    totals: tuple
    row_count: int


def _sort_key(value):
    # empty values last; numbers before text
    if value is None:
        return (2, 0, "")
    if isinstance(value, (int, float)):
        return (0, value, "")
    return (1, 0, str(value).lower())


def _sums(columns, sum_columns, rows) -> tuple:
    result = []
    for i, name in enumerate(columns):
        if name in sum_columns:
            numbers = [r[i] for r in rows if isinstance(r[i], (int, float))]
            result.append(sum(numbers) if numbers else 0)
        else:
            result.append(None)
    return tuple(result)


def build_report(definition: ReportDef, names: list[str], rows: list[tuple]) -> ReportData:
    """Group, sort and total `rows` (whose columns are `names`) as the report asks."""
    columns = tuple(c for c in (definition.columns or names) if c in names)
    index = {n: i for i, n in enumerate(names)}
    picked = [tuple(r[index[c]] for c in columns) for r in rows]
    group_col = definition.group_by if definition.group_by in names else ""
    group_values = [r[index[group_col]] for r in rows] if group_col else [None] * len(rows)
    sort_col = definition.sort_by if definition.sort_by in names else ""
    sort_values = [r[index[sort_col]] for r in rows] if sort_col else [None] * len(rows)
    order = sorted(range(len(rows)), key=lambda i: _sort_key(sort_values[i]),
                   reverse=definition.descending)
    if group_col:  # stable: groups ascending, rows keep the chosen order within a group
        order = sorted(order, key=lambda i: _sort_key(group_values[i]))
    groups: list[ReportGroup] = []
    if group_col:
        buckets: dict = {}
        for i in order:
            buckets.setdefault(group_values[i], []).append(picked[i])
        for key, members in buckets.items():
            groups.append(ReportGroup(key, tuple(members),
                                      _sums(columns, definition.sum_columns, members)))
    else:
        members = [picked[i] for i in order]
        groups.append(ReportGroup(None, tuple(members),
                                  _sums(columns, definition.sum_columns, members)))
    return ReportData(columns, group_col, tuple(groups),
                      _sums(columns, definition.sum_columns, picked), len(picked))

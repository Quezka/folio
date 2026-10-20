"""The open database: tables, rows, saved queries, forms and reports."""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Callable

from ..domain import objects as dom_objects
from ..domain import query as dom_query
from ..domain.schema import (DEFAULT_CURRENCY, Field, FieldType, ForeignKey, Table, relationships,
                             validate_table, SchemaError)
from ..domain.values import InvalidValueError, coerce, detect_currency, guess_type
from .errors import (ApplicationError, ConstraintError, DesignError, IncompleteRowError, NotFound,
                     NotOpenError)
from . import inputs as app
from .inputs import FieldDesign, ImportSpec, TableDesign
from .ports import (AccessColumn, AccessDatabase, AccessFiles, AccessLink, AccessTable, CsvFiles,
                    DatabaseGateway, KeyValueStore, RowQuery)
from .records import (ColumnRecord, CsvPreview, FieldRecord, LookupOption, PageRecord,
                      QueryRecord, RelationshipRecord, ReportGroup, ReportView, RowRecord,
                      TableRecord)

PAGE = 200
REPORT_LIMIT = 100_000
RECENT = 10


class Change(Enum):
    OPENED = "opened"
    CLOSED = "closed"
    SCHEMA = "schema"  # tables or their design changed
    DATA = "data"  # rows changed
    OBJECTS = "objects"  # saved queries, forms or reports changed


@dataclass(frozen=True)
class Source:
    """Something with rows: a table, or a saved query."""
    kind: str  # "table" | "query" (saved) | "sql" (name is the SELECT itself)
    name: str


@dataclass(frozen=True)
class ImportResult:
    table: str
    rows: int
    problems: int  # values that didn't fit their field and were left empty


@dataclass(frozen=True)
class AccessImport:
    tables: tuple[ImportResult, ...]
    links: int  # relationships carried over
    links_lost: int  # relationships that couldn't be (the other table or key is missing)
    skipped_columns: int  # pictures, attachments and other things Folio can't hold
    links_inferred: int = 0  # relationships the file didn't declare but its data and names show


@dataclass(frozen=True)
class AccessExport:
    tables: int
    rows: int
    links: int


_FROM_ACCESS = {"autonumber": FieldType.INTEGER, "integer": FieldType.INTEGER,
                "number": FieldType.NUMBER, "currency": FieldType.CURRENCY, "boolean": FieldType.YES_NO, "date": FieldType.DATE,
                "datetime": FieldType.DATETIME, "text": FieldType.TEXT,
                "longtext": FieldType.LONG_TEXT}
_TO_ACCESS = {FieldType.INTEGER: "integer", FieldType.NUMBER: "number",
              FieldType.CURRENCY: "currency",
              FieldType.YES_NO: "boolean", FieldType.DATE: "date", FieldType.DATETIME: "datetime",
              FieldType.TEXT: "text", FieldType.LONG_TEXT: "longtext"}


def _stem_matches(stem: str, table: str) -> bool:
    """Does a column name like "ID_Negozio" / "CatenaId" point at a table called "Negozi"?"""
    a, b = stem.lower(), table.lower()
    if len(a) < 3 or len(b) < 3:
        return False
    return (a == b or a[:-1] == b or b[:-1] == a or a[:-1] == b[:-1] or a + "s" == b or b + "s" == a
            or a + "es" == b)


def _column_stem(name: str) -> str:
    import re
    return re.sub(r"(^id[_ ]?|[_ ]?id$)", "", name, flags=re.I)


def _guess_links(source: AccessDatabase, declared: set[tuple[str, str]]):
    """Links an Access file never declared: a column whose name echoes a table (ID_Negozio ->
    Negozi) or a key (CF), and whose values all exist in that table's single-column key."""
    keys = {}
    for t in source.tables:
        pk = [i for i, c in enumerate(t.columns) if c.key]
        if len(pk) == 1:
            i = pk[0]
            keys[t.name] = (t.columns[i], {r[i] for r in t.rows if r[i] is not None})
    textual = {"text"}
    for t in source.tables:
        for i, c in enumerate(t.columns):
            if (t.name, c.name) in declared or c.kind not in ("integer", "autonumber", "text"):
                continue
            if c.kind == "autonumber" or t.name in keys and keys[t.name][0] is c:
                continue  # a table's own key identifies it; it doesn't point elsewhere
            values = {r[i] for r in t.rows if r[i] is not None}
            if not values:
                continue
            found = []
            for parent, (key, key_values) in keys.items():
                if parent == t.name or (key.kind in textual) != (c.kind in textual):
                    continue
                if not values <= key_values:
                    continue
                same_name = c.name.lower() == key.name.lower()
                echoes = _stem_matches(_column_stem(c.name), parent) and c.name.lower() != "id"
                if same_name or echoes:
                    found.append((parent, key.name))
            if len(found) == 1:
                yield t.name, c.name, found[0][0], found[0][1]


@dataclass
class _Undo:
    label: str
    undo: Callable[[], None]
    redo: Callable[[], None]


# ---- the application's data classes <-> the domain's (same fields, different layer) ---------

def _query_to_domain(d: app.QueryDesign) -> dom_query.QueryDesign:
    return dom_query.QueryDesign(
        tuple(d.tables), tuple(dom_query.Join(**vars(j)) for j in d.joins),
        tuple(dom_query.QueryColumn(**vars(c)) for c in d.columns), d.distinct)


def _query_from_domain(d: dom_query.QueryDesign) -> app.QueryDesign:
    return app.QueryDesign(
        tuple(d.tables), tuple(app.Join(**vars(j)) for j in d.joins),
        tuple(app.QueryColumn(**vars(c)) for c in d.columns), d.distinct)


def _form_to_domain(f: app.FormDef) -> dom_objects.FormDef:
    return dom_objects.FormDef(f.source, f.source_kind, f.title,
                               tuple(dom_objects.FormField(**vars(x)) for x in f.fields), f.columns)


def _form_from_domain(f: dom_objects.FormDef) -> app.FormDef:
    return app.FormDef(f.source, f.source_kind, f.title,
                       tuple(app.FormField(**vars(x)) for x in f.fields), f.columns)


def _report_to_domain(r: app.ReportDef) -> dom_objects.ReportDef:
    return dom_objects.ReportDef(**vars(r))


def _report_from_domain(r: dom_objects.ReportDef) -> app.ReportDef:
    return app.ReportDef(**vars(r))


def _alias_pk(table: Table) -> bool:
    """True when the table's key is the row id itself (an INTEGER PRIMARY KEY)."""
    pk = table.primary_key
    return len(pk) == 1 and pk[0].type is FieldType.INTEGER


class Workspace:
    def __init__(self, db: DatabaseGateway, csv: CsvFiles, access: AccessFiles,
                 settings: KeyValueStore):
        self._db = db
        self._csv = csv
        self._access = access
        self._settings = settings
        self._listeners: list[Callable[[Change], None]] = []
        self._undo: list[_Undo] = []
        self._redo: list[_Undo] = []
        self._schema_cache: list[Table] | None = None

    # ---- notices -------------------------------------------------------------------
    def subscribe(self, listener: Callable[[Change], None]) -> None:
        self._listeners.append(listener)

    def _emit(self, change: Change) -> None:
        for listener in list(self._listeners):
            listener(change)

    # ---- the file ------------------------------------------------------------------
    @property
    def path(self) -> str | None:
        return self._db.path

    @property
    def is_open(self) -> bool:
        return self._db.path is not None

    @property
    def name(self) -> str:
        return Path(self._db.path).stem if self._db.path else ""

    def _opened(self):
        self._undo.clear()
        self._redo.clear()
        self._schema_cache = None
        self._remember(self._db.path)
        self._emit(Change.OPENED)

    def create(self, path: str) -> None:
        self._db.create(path)
        self._opened()

    def open(self, path: str) -> None:
        self._db.open(path)
        self._opened()

    def close(self) -> None:
        self._db.close()
        self._undo.clear()
        self._redo.clear()
        self._schema_cache = None
        self._emit(Change.CLOSED)

    def compact(self) -> None:
        self._db.compact()

    def recent(self) -> list[str]:
        try:
            items = json.loads(self._settings.get("recent") or "[]")
        except ValueError:
            return []
        return [p for p in items if isinstance(p, str) and Path(p).exists()]

    def _remember(self, path: str | None) -> None:
        if not path:
            return
        items = [path] + [p for p in self.recent() if p != path]
        self._settings.set("recent", json.dumps(items[:RECENT]))

    def forget(self, path: str) -> None:
        self._settings.set("recent", json.dumps([p for p in self.recent() if p != path]))

    # ---- structure -----------------------------------------------------------------
    def _schema(self) -> list[Table]:
        if not self.is_open:
            raise NotOpenError("No database is open.")
        if self._schema_cache is None:
            self._schema_cache = self._db.read_schema()
        return self._schema_cache

    def _table(self, name: str) -> Table:
        for t in self._schema():
            if t.name == name:
                return t
        raise NotFound("That table doesn't exist any more.")

    @staticmethod
    def _field_record(t: Table, f: Field) -> FieldRecord:
        key = t.foreign_key(f.name)
        return FieldRecord(f.name, f.type, f.primary_key, f.autonumber, f.required, f.unique,
                           f.default or "", key.ref_table if key else "",
                           key.ref_field if key else "", key.on_delete if key else "NO ACTION",
                           f.currency)

    def tables(self) -> list[TableRecord]:
        return [self.table(t.name) for t in self._schema()]

    def table(self, name: str) -> TableRecord:
        t = self._table(name)
        count = self._db.count_table(t, RowQuery())
        return TableRecord(t.name, tuple(self._field_record(t, f) for f in t.fields), count,
                           t.locked)

    def table_names(self) -> list[str]:
        return [t.name for t in self._schema()]

    def relationships(self) -> list[RelationshipRecord]:
        return [RelationshipRecord(r.child, r.child_field, r.parent, r.parent_field, r.on_delete)
                for r in relationships(self._schema())]

    def _to_table(self, design: TableDesign) -> Table:
        fields, keys = [], []
        for f in design.fields:
            primary = f.primary_key or f.autonumber
            fields.append(Field(f.name.strip(), f.type, primary, f.autonumber, f.required,
                                f.unique, f.default.strip() or None,
                                (f.currency or DEFAULT_CURRENCY) if f.type is FieldType.CURRENCY else ""))
            if f.ref_table:
                keys.append(ForeignKey(f.name.strip(), f.ref_table, f.ref_field, f.on_delete))
        return Table(design.name.strip(), tuple(fields), tuple(keys))

    def save_table(self, original: str | None, design: TableDesign) -> None:
        """Create a table (original=None) or change an existing one, keeping its rows."""
        table = self._to_table(design)
        schema = self._schema()
        try:
            validate_table(table)
        except SchemaError as e:
            raise DesignError(str(e)) from e
        if any(t.name.lower() == table.name.lower() and t.name != original for t in schema):
            raise DesignError("There is already a table with that name.")
        for key in table.foreign_keys:
            parent = table if key.ref_table == table.name else next(
                (t for t in schema if t.name == key.ref_table), None)
            target = parent.field(key.ref_field) if parent else None
            if target is None or not (target.primary_key or target.unique):
                raise DesignError("A link must point at a key (primary or unique) field of "
                                  "another table.")
        if original is None:
            self._db.create_table(table)
        else:
            old = self._table(original)
            if old.locked:
                raise DesignError("This table uses features Folio's designer can't keep, so "
                                  "only its rows can be edited here.")
            kept = {f.original_name for f in design.fields if f.original_name}
            renamed = {f.original_name for f in design.fields
                       if f.original_name and f.original_name != f.name.strip()}
            for other in schema:
                for key in other.foreign_keys:
                    if key.ref_table == original and other.name != original and (
                            key.ref_field not in kept or key.ref_field in renamed):
                        raise DesignError("Another table links to a field you removed or "
                                          "renamed. Remove that link first.")
            self._db.rebuild_table(original, table,
                                   {f.name.strip(): f.original_name for f in design.fields})
            if original != table.name:
                self._rename_sources(original, table.name)
        self._schema_cache = None
        self._undo.clear()
        self._redo.clear()
        self._emit(Change.SCHEMA)

    def _retarget(self, source_kind: str, old: str, new: str) -> None:
        for kind in ("form", "report"):
            for name in self._db.list_objects(kind):
                data = self._db.load_object(kind, name)
                if data and data.get("source_kind", "table") == source_kind and data["source"] == old:
                    self._db.save_object(kind, name, {**data, "source": new})

    def _rename_sources(self, old: str, new: str) -> None:
        """Forms and reports that used a renamed table follow it."""
        self._retarget("table", old, new)

    def drop_table(self, name: str) -> None:
        for other in self._schema():
            if other.name != name and any(k.ref_table == name for k in other.foreign_keys):
                raise DesignError("Other tables link to this one. Remove those links first.")
        self._db.drop_table(name)
        for kind in ("form", "report"):
            for obj in self._db.list_objects(kind):
                data = self._db.load_object(kind, obj)
                if data and data.get("source_kind", "table") == "table" and data["source"] == name:
                    self._db.delete_object(kind, obj)
        self._schema_cache = None
        self._undo.clear()
        self._redo.clear()
        self._emit(Change.SCHEMA)
        self._emit(Change.OBJECTS)

    # ---- rows ----------------------------------------------------------------------
    def _query_sql(self, source: Source) -> str:
        if source.kind == "sql":  # a query that isn't saved (yet)
            return source.name
        if source.kind != "query":
            raise NotFound("That query doesn't exist any more.")
        return self.query(source.name).sql

    def columns(self, source: Source) -> list[ColumnRecord]:
        if source.kind == "table":
            t = self._table(source.name)
            return [ColumnRecord(f.name, f.type,
                                 (t.foreign_key(f.name).ref_table if t.foreign_key(f.name) else ""),
                                 not f.autonumber, f.required, f.currency) for f in t.fields]
        return [self._query_column(n) for n in self._db.check_select(self._query_sql(source))]

    def _query_column(self, name: str) -> ColumnRecord:
        """A query column, typed like the table field it's named after when that's unambiguous
        (so money stays money and dates stay dates in the results)."""
        base = name
        for prefix in ("Sum of ", "Average of ", "Min of ", "Max of "):
            if name.startswith(prefix):
                base = name[len(prefix):]
        if name.startswith("Count of "):
            return ColumnRecord(name, FieldType.INTEGER, "", False)
        found = {(f.type, f.currency) for t in self._schema() for f in t.fields
                 if f.name.lower() == base.lower() and not (t.foreign_key(f.name) or f.type is FieldType.YES_NO and False)}
        if len(found) == 1:
            ftype, currency = next(iter(found))
            return ColumnRecord(name, ftype, "", False, False, currency)
        return ColumnRecord(name, None, "", False)

    def page(self, source: Source, query: RowQuery = RowQuery(), offset: int = 0,
             limit: int = PAGE) -> PageRecord:
        if source.kind == "table":
            t = self._table(source.name)
            rows = self._db.fetch_table(t, query, offset, limit)
            total = self._db.count_table(t, query)
            return PageRecord(tuple(self.columns(source)),
                              tuple(RowRecord(r[0], tuple(r[1:])) for r in rows), total)
        sql = self._query_sql(source)
        names, rows = self._db.fetch_query(sql, query, offset, limit)
        total = self._db.count_query(sql, query)
        return PageRecord(tuple(self._query_column(n) for n in names),
                          tuple(RowRecord(None, tuple(r)) for r in rows), total)

    def lookup(self, table: str, key_field: str | None = None) -> list[LookupOption]:
        """The rows of a table as choices for a field that links to it."""
        t = self._table(table)
        key = key_field or (t.primary_key[0].name if t.primary_key else None)
        if key is None:
            return []
        label = t.label_field() or key
        return [LookupOption(k, "" if lab is None else str(lab))
                for k, lab in self._db.lookup(t, key, label)]

    def _values(self, t: Table, texts: dict[str, str]) -> dict:
        values = {}
        for name, text in texts.items():
            f = t.field(name)
            if f is None:
                raise NotFound("That field doesn't exist any more.")
            try:
                values[name] = coerce(text, f.type)
            except InvalidValueError as e:
                raise DesignError(str(e)) from e
        return values

    def _push(self, entry: _Undo) -> None:
        self._undo.append(entry)
        del self._undo[:-200]
        self._redo.clear()

    def update_cell(self, table: str, row_id: int, field: str, text: str) -> None:
        t = self._table(table)
        new = self._values(t, {field: text})
        old = self._db.get_row(t, row_id)
        if old is None:
            raise NotFound("That row doesn't exist any more.")
        self._db.update_row(t, row_id, new)
        before = {field: old[field]}
        self._push(_Undo(f"edit {field}", lambda: self._db.update_row(t, row_id, before),
                         lambda: self._db.update_row(t, row_id, new)))
        self._emit(Change.DATA)

    def insert_row(self, table: str, texts: dict[str, str]) -> int:
        t = self._table(table)
        values = {k: v for k, v in self._values(t, texts).items() if v is not None}
        missing = [f.name for f in t.fields if f.required and values.get(f.name) is None
                   and not f.default]
        if missing:
            raise IncompleteRowError("Fill in the required fields first.")
        row_id = self._db.insert_row(t, values)
        stored = self._db.get_row(t, row_id) or values
        self._push(_Undo("new row", lambda: self._db.delete_rows(t, [row_id]),
                         lambda: self._restore(t, row_id, stored)))
        self._emit(Change.DATA)
        return row_id

    def _restore(self, t: Table, row_id: int, values: dict) -> None:
        self._db.insert_row(t, values, None if _alias_pk(t) else row_id)

    def delete_rows(self, table: str, row_ids: list[int]) -> None:
        t = self._table(table)
        saved = [(r, self._db.get_row(t, r)) for r in row_ids]
        saved = [(r, v) for r, v in saved if v is not None]
        self._db.delete_rows(t, [r for r, _ in saved])

        def redo():
            self._db.delete_rows(t, [r for r, _ in saved])

        def undo():
            for r, v in saved:
                self._restore(t, r, v)

        self._push(_Undo("delete rows", undo, redo))
        self._emit(Change.DATA)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        entry = self._undo.pop()
        try:
            entry.undo()
        except ConstraintError:
            self._undo.clear()
            raise
        self._redo.append(entry)
        self._emit(Change.DATA)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        entry = self._redo.pop()
        try:
            entry.redo()
        except ConstraintError:
            self._redo.clear()
            raise
        self._undo.append(entry)
        self._emit(Change.DATA)
        return True

    # ---- saved queries -------------------------------------------------------------
    def _objects(self, kind: str) -> list[str]:
        if not self.is_open:
            raise NotOpenError("No database is open.")
        return self._db.list_objects(kind)

    def queries(self) -> list[str]:
        return self._objects("query")

    def build_sql(self, design: app.QueryDesign) -> str:
        """The SQL a visual query stands for."""
        try:
            return dom_query.to_sql(_query_to_domain(design), self._schema())
        except dom_query.QueryError as e:
            raise DesignError(str(e)) from e

    def suggest_joins(self, tables: list[str], existing=()) -> tuple[app.Join, ...]:
        joins = dom_query.auto_joins(tables, self._schema(),
                                     tuple(dom_query.Join(**vars(j)) for j in existing))
        return tuple(app.Join(**vars(j)) for j in joins)

    def check_sql(self, sql: str) -> list[str]:
        """The columns a SELECT gives, or DesignError if it can't run."""
        return self._db.check_select(sql)

    def query(self, name: str) -> QueryRecord:
        data = self._db.load_object("query", name)
        if data is None:
            raise NotFound("That query doesn't exist any more.")
        design = (_query_from_domain(dom_query.design_from_dict(data["design"]))
                  if data.get("design") else None)
        return QueryRecord(name, data["sql"], design)

    def save_query(self, name: str, original: str | None, sql: str,
                   design: app.QueryDesign | None = None) -> None:
        name = name.strip()
        if not name:
            raise DesignError("Give the query a name.")
        if name != original and any(n.lower() == name.lower() for n in self.queries()):
            raise DesignError("There is already a query with that name.")
        self._db.check_select(sql)
        if original and original != name:
            self._db.delete_object("query", original)
            self._rename_query_sources(original, name)
        self._db.save_object("query", name, {
            "sql": sql,
            "design": dom_query.design_to_dict(_query_to_domain(design)) if design else None})
        self._emit(Change.OBJECTS)

    def _rename_query_sources(self, old: str, new: str) -> None:
        self._retarget("query", old, new)

    def delete_query(self, name: str) -> None:
        self._db.delete_object("query", name)
        self._emit(Change.OBJECTS)

    # ---- forms and reports ---------------------------------------------------------
    def forms(self) -> list[str]:
        return self._objects("form")

    def form(self, name: str) -> app.FormDef:
        data = self._db.load_object("form", name)
        if data is None:
            raise NotFound("That form doesn't exist any more.")
        return _form_from_domain(dom_objects.form_from_dict(data))

    def default_form(self, source: Source) -> app.FormDef:
        fields = tuple(app.FormField(c.name, c.name, not c.editable) for c in self.columns(source))
        return app.FormDef(source.name, source.kind, source.name, fields,
                           2 if len(fields) > 6 else 1)

    def save_form(self, name: str, original: str | None, form: app.FormDef) -> None:
        name = name.strip()
        if not name:
            raise DesignError("Give the form a name.")
        if name != original and any(n.lower() == name.lower() for n in self.forms()):
            raise DesignError("There is already a form with that name.")
        if not form.fields:
            raise DesignError("Pick at least one field for the form.")
        if original and original != name:
            self._db.delete_object("form", original)
        self._db.save_object("form", name, dom_objects.form_to_dict(_form_to_domain(form)))
        self._emit(Change.OBJECTS)

    def delete_form(self, name: str) -> None:
        self._db.delete_object("form", name)
        self._emit(Change.OBJECTS)

    def reports(self) -> list[str]:
        return self._objects("report")

    def report(self, name: str) -> app.ReportDef:
        data = self._db.load_object("report", name)
        if data is None:
            raise NotFound("That report doesn't exist any more.")
        return _report_from_domain(dom_objects.report_from_dict(data))

    def default_report(self, source: Source) -> app.ReportDef:
        return app.ReportDef(source.name, source.kind, source.name,
                             tuple(c.name for c in self.columns(source)))

    def save_report(self, name: str, original: str | None, report: app.ReportDef) -> None:
        name = name.strip()
        if not name:
            raise DesignError("Give the report a name.")
        if name != original and any(n.lower() == name.lower() for n in self.reports()):
            raise DesignError("There is already a report with that name.")
        if not report.columns:
            raise DesignError("Pick at least one column for the report.")
        if original and original != name:
            self._db.delete_object("report", original)
        self._db.save_object("report", name, dom_objects.report_to_dict(_report_to_domain(report)))
        self._emit(Change.OBJECTS)

    def delete_report(self, name: str) -> None:
        self._db.delete_object("report", name)
        self._emit(Change.OBJECTS)

    def _all_rows(self, source: Source, limit: int) -> tuple[list[str], list[tuple]]:
        """Every row of a source with links replaced by what they point at."""
        if source.kind == "query":
            names, rows = self._db.fetch_query(self._query_sql(source), RowQuery(), 0, limit)
            return names, [tuple(r) for r in rows]
        t = self._table(source.name)
        rows = [list(r[1:]) for r in self._db.fetch_table(t, RowQuery(), 0, limit)]
        for i, f in enumerate(t.fields):
            key = t.foreign_key(f.name)
            if key is not None and any(tt.name == key.ref_table for tt in self._schema()):
                labels = {o.key: o.label for o in self.lookup(key.ref_table, key.ref_field)}
                for r in rows:
                    r[i] = labels.get(r[i], r[i])
        return [f.name for f in t.fields], [tuple(r) for r in rows]

    def rows_of(self, source: Source, limit: int = REPORT_LIMIT) -> tuple[list[str], list[tuple]]:
        return self._all_rows(source, limit)

    def build_report(self, report: app.ReportDef) -> ReportView:
        names, rows = self._all_rows(Source(report.source_kind, report.source), REPORT_LIMIT)
        built = dom_objects.build_report(_report_to_domain(report), names, rows)
        return ReportView(built.columns, built.group_by,
                          tuple(ReportGroup(g.key, g.rows, g.sums) for g in built.groups),
                          built.totals, built.row_count)

    # ---- the relationships diagram ---------------------------------------------------
    def layout(self) -> dict:
        return self._db.load_object("layout", "relationships") or {}

    def save_layout(self, positions: dict) -> None:
        self._db.save_object("layout", "relationships", positions)

    # ---- CSV -----------------------------------------------------------------------
    @staticmethod
    def _names(header: list[str]) -> list[str]:
        result, seen = [], set()
        for i, h in enumerate(header, 1):
            name = h.strip() or f"Column {i}"
            base, n = name, 2
            while name.lower() in seen:
                name, n = f"{base}_{n}", n + 1
            seen.add(name.lower())
            result.append(name)
        return result

    def preview_csv(self, path: str, has_header: bool = True) -> CsvPreview:
        rows = self._csv.read(path)
        if not rows:
            raise DesignError("That file is empty.")
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        header = self._names(rows[0]) if has_header else [f"Column {i}" for i in range(1, width + 1)]
        data = rows[1:] if has_header else rows
        types = tuple(guess_type([r[i] for r in data[:2000]]) for i in range(width))
        currencies = tuple((detect_currency([r[i] for r in data[:2000]]) or DEFAULT_CURRENCY)
                           if types[i] is FieldType.CURRENCY else "" for i in range(width))
        return CsvPreview(tuple(header), tuple(tuple(r) for r in data[:20]), types, currencies,
                          len(data))

    def import_csv(self, spec: ImportSpec) -> ImportResult:
        rows = self._csv.read(spec.path)
        data = rows[1:] if spec.has_header else rows
        name = spec.table.strip()
        if not name or not spec.fields:
            raise DesignError("Give the table a name and keep at least one column.")
        if spec.append:
            t = self._table(name)
            for f in spec.fields:
                if t.field(f.name) is None:
                    raise DesignError("A column doesn't match any field of that table.")
        else:
            fields = [FieldDesign(f.name, f.type, currency=f.currency) for f in spec.fields]
            if spec.add_key:
                key_name = "id"
                while any(f.name.lower() == key_name for f in spec.fields):
                    key_name += "_"
                fields.insert(0, FieldDesign(key_name, FieldType.INTEGER, True, True))
            self.save_table(None, TableDesign(name, tuple(fields)))
            t = self._table(name)
        problems, out = 0, []
        for row in data:
            record = []
            for f in spec.fields:
                text = row[f.column] if f.column < len(row) else ""
                ftype = t.field(f.name).type
                try:
                    record.append(coerce(text, ftype))
                except InvalidValueError:
                    record.append(None)
                    problems += 1
            out.append(record)
        try:
            self._db.bulk_insert(t, [f.name for f in spec.fields], out)
        except ConstraintError:
            if not spec.append:
                self.drop_table(name)
            raise
        self._schema_cache = None
        self._emit(Change.DATA)
        return ImportResult(name, len(out), problems)

    def export_csv(self, source: Source, path: str) -> int:
        names, rows = self._all_rows(source, 10_000_000)
        self._csv.write(path, names, [list(r) for r in rows])
        return len(rows)

    # ---- Access --------------------------------------------------------------------
    def import_access(self, path: str) -> AccessImport:
        """Copy every table (and relationship) of an Access file into the open database."""
        source = self._access.read(path)
        results, names = [], {}
        skipped_columns = 0
        for table in source.tables:
            if not table.columns:
                continue
            result = self._import_access_table(table)
            names[table.name] = result.table
            results.append(result)
            skipped_columns += len(table.skipped)
        linked = lost = 0
        for link in source.links:
            if self._link(names.get(link.child), link.child_field, names.get(link.parent),
                          link.parent_field, link.cascade, link.set_null):
                linked += 1
            else:
                lost += 1
        inferred = 0
        for child, field, parent, parent_field in _guess_links(source, {
                (l.child, l.child_field) for l in source.links}):
            if self._link(names.get(child), field, names.get(parent), parent_field, False, False):
                inferred += 1
        self._schema_cache = None
        self._emit(Change.SCHEMA)
        return AccessImport(tuple(results), linked, lost, skipped_columns, inferred)

    def _import_access_table(self, source: AccessTable) -> ImportResult:
        existing = {n.lower() for n in self.table_names()}
        name, n = source.name, 2
        while name.lower() in existing:
            name, n = f"{source.name}_{n}", n + 1
        names = self._names([c.name for c in source.columns])
        keys = [c for c in source.columns if c.key]
        fields, types = [], []
        for fname, c in zip(names, source.columns):
            ftype = _FROM_ACCESS[c.kind]
            single = len(keys) == 1 and c.key
            fields.append(FieldDesign(fname, ftype, primary_key=c.key,
                                      autonumber=single and c.kind == "autonumber",
                                      required=c.required and not c.key, unique=c.unique and not c.key,
                                      currency=c.currency or (DEFAULT_CURRENCY if ftype is FieldType.CURRENCY else "")))
            types.append(ftype)
        self.save_table(None, TableDesign(name, tuple(fields)))
        t = self._table(name)
        problems, out = 0, []
        for row in source.rows:
            record = []
            for value, ftype in zip(row, types):
                try:
                    record.append(self._access_value(value, ftype))
                except InvalidValueError:
                    record.append(None)
                    problems += 1
            out.append(record)
        if out:
            self._db.bulk_insert(t, names, out)
        return ImportResult(name, len(out), problems)

    @staticmethod
    def _access_value(value, ftype: FieldType):
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if ftype in (FieldType.TEXT, FieldType.LONG_TEXT):
            return str(value)
        if ftype in (FieldType.NUMBER, FieldType.CURRENCY):
            return float(value)
        return coerce(value if isinstance(value, str) else str(value), ftype)

    def _link(self, child: str | None, child_field: str, parent: str | None, parent_field: str,
              cascade: bool, set_null: bool) -> bool:
        """Make `child.child_field` point at `parent.parent_field`; False if that can't be done."""
        if not child or not parent:
            return False
        try:
            record = self.table(child)
            if record.field(child_field) is None or self.table(parent).field(parent_field) is None:
                return False
            action = "CASCADE" if cascade else ("SET NULL" if set_null else "NO ACTION")
            fields = tuple(
                FieldDesign(f.name, f.type, f.primary_key, f.autonumber, f.required, f.unique,
                            f.default, f.currency, f.name,
                            parent if f.name == child_field else f.ref_table,
                            parent_field if f.name == child_field else f.ref_field,
                            action if f.name == child_field else f.on_delete)
                for f in record.fields)
            self.save_table(child, TableDesign(child, fields))
            return True
        except ApplicationError:
            return False  # e.g. the parent field isn't a key, or rows point at nothing

    def export_access(self, path: str) -> AccessExport:
        """Create a new Access file (.accdb) holding every table, its rows and its relationships."""
        tables, links = [], []
        for t in self._schema():
            rows = [r[1:] for r in self._db.fetch_table(t, RowQuery(), 0, 2 ** 31 - 1)]
            columns, kinds = [], []
            for i, f in enumerate(t.fields):
                kind = _TO_ACCESS[f.type]
                values = [r[i] for r in rows if r[i] is not None]
                if f.autonumber:
                    kind = "autonumber"
                elif f.type is FieldType.TEXT and any(len(str(v)) > 255 for v in values):
                    kind = "longtext"
                elif f.type is FieldType.INTEGER and any(abs(v) >= 2 ** 31 for v in values):
                    kind = "number"  # Access whole numbers are 32 bits
                kinds.append(kind)
                columns.append(AccessColumn(f.name, kind, f.primary_key, f.unique, f.required,
                                            f.currency or DEFAULT_CURRENCY if kind == "currency" else ""))
            data = tuple(tuple(self._for_access(v, k) for v, k in zip(r, kinds)) for r in rows)
            tables.append(AccessTable(t.name, tuple(columns), data))
            for key in t.foreign_keys:
                links.append(AccessLink(t.name, key.field, key.ref_table, key.ref_field,
                                        key.on_delete == "CASCADE", key.on_delete == "SET NULL"))
        self._access.write(path, AccessDatabase(tuple(tables), tuple(links)))
        return AccessExport(len(tables), sum(len(t.rows) for t in tables), len(links))

    @staticmethod
    def _for_access(value, kind: str):
        if value is None:
            return None
        if kind == "boolean":
            return bool(value)
        if kind in ("number", "currency"):
            return float(value)
        if kind in ("integer", "autonumber"):
            return int(value)
        return str(value)

"""Visual queries: pick fields, type criteria, get SQL."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .schema import FieldType, Table, literal, quote
from .values import InvalidValueError, coerce

TOTALS = ("", "group", "sum", "avg", "min", "max", "count")
SORTS = ("", "asc", "desc")
JOIN_KINDS = ("inner", "left")


class QueryError(Exception):
    """A query design that can't be turned into SQL (the message is shown)."""


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


# ---- criteria -----------------------------------------------------------------------

_OPERATORS = ("<>", "!=", ">=", "<=", "=", ">", "<")
_BAD = "A criterion isn't written correctly."


def _split_top(text: str, word: str) -> list[str]:
    """Split on a keyword outside quotes and parentheses."""
    parts, depth, quote_char, start, i = [], 0, "", 0, 0
    pattern = re.compile(rf"\s{word}\s", re.I)
    while i < len(text):
        c = text[i]
        if quote_char:
            if c == quote_char:
                quote_char = ""
        elif c in "\"'#":
            quote_char = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0 and c.isspace():
            m = pattern.match(text, i)
            if m:
                parts.append(text[start:i])
                start = m.end()
                i = m.end() - 1
        i += 1
    parts.append(text[start:])
    return parts


def _value(text: str, ftype: FieldType) -> str:
    """One value of a criterion as an SQL literal."""
    text = text.strip()
    if text == "":
        raise QueryError(_BAD)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'#":
        text = text[1:-1]
    elif ftype is FieldType.DATE and text.lower() in ("today", "date()"):
        return "date('now','localtime')"
    elif ftype is FieldType.DATETIME and text.lower() in ("now", "today"):
        return "datetime('now','localtime')"
    try:
        value = coerce(text, ftype)
    except InvalidValueError:
        raise QueryError("A criterion has a value that doesn't fit the field's type.") from None
    return literal(value)


def _like_pattern(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    return literal(text.replace("%", "\\%").replace("_", "\\_").replace("*", "%").replace("?", "_"))


def _simple(expr: str, text: str, ftype: FieldType) -> str:
    text = text.strip()
    low = text.lower()
    if low.startswith("not "):
        return f"NOT ({_simple(expr, text[4:], ftype)})"
    if low in ("null", "is null", "empty"):
        return f"{expr} IS NULL"
    if low in ("not null", "is not null"):
        return f"{expr} IS NOT NULL"
    m = re.fullmatch(r"between\s+(.+?)\s+and\s+(.+)", text, re.I)
    if m:
        return f"{expr} BETWEEN {_value(m.group(1), ftype)} AND {_value(m.group(2), ftype)}"
    m = re.fullmatch(r"in\s*\((.*)\)", text, re.I)
    if m:
        items = [i for i in _split_commas(m.group(1))]
        if not items:
            raise QueryError(_BAD)
        return f"{expr} IN ({', '.join(_value(i, ftype) for i in items)})"
    m = re.match(r"like\s+(.+)", text, re.I)
    if m:
        return f"{expr} LIKE {_like_pattern(m.group(1))} ESCAPE '\\'"
    for op in _OPERATORS:
        if text.startswith(op):
            rest = text[len(op):]
            sql_op = "<>" if op == "!=" else op
            suffix = " COLLATE NOCASE" if ftype in (FieldType.TEXT, FieldType.LONG_TEXT) \
                and sql_op in ("=", "<>") else ""
            return f"{expr} {sql_op} {_value(rest, ftype)}{suffix}"
    if ftype in (FieldType.TEXT, FieldType.LONG_TEXT) and re.search(r"[*?]", text):
        return f"{expr} LIKE {_like_pattern(text)} ESCAPE '\\'"
    suffix = " COLLATE NOCASE" if ftype in (FieldType.TEXT, FieldType.LONG_TEXT) else ""
    return f"{expr} = {_value(text, ftype)}{suffix}"


def _split_commas(text: str) -> list[str]:
    items, current, quote_char = [], "", ""
    for c in text:
        if quote_char:
            current += c
            if c == quote_char:
                quote_char = ""
        elif c in "\"'":
            quote_char = c
            current += c
        elif c == ",":
            items.append(current.strip())
            current = ""
        else:
            current += c
    if current.strip():
        items.append(current.strip())
    return items


def criterion_sql(expr: str, text: str, ftype: FieldType) -> str:
    """SQL for one criteria cell, e.g. `>= 5 and < 10`, `like "A*"`, `"Rome" or "Milan"`."""
    text = (text or "").strip()
    if not text:
        return ""
    # a BETWEEN's own "and" must not split the cell
    shielded = re.sub(r"(between\s+.+?)\s+and\s+", lambda m: m.group(1) + " \x00 ", text,
                      flags=re.I)
    ors = []
    for part in _split_top(shielded, "or"):
        ands = [_simple(expr, a.replace("\x00", "and"), ftype)
                for a in _split_top(part, "and")]
        ors.append(" AND ".join(ands) if len(ands) == 1 else "(" + " AND ".join(ands) + ")")
    return ors[0] if len(ors) == 1 else "(" + " OR ".join(ors) + ")"


# ---- SQL ----------------------------------------------------------------------------

def auto_joins(tables: list[str], schema: list[Table], existing: tuple[Join, ...] = ()) -> tuple[Join, ...]:
    """Joins that follow the relationships between the chosen tables."""
    by_name = {t.name: t for t in schema}
    joins = list(existing)
    have = {(j.left_table, j.left_field, j.right_table, j.right_field) for j in joins}
    for name in tables:
        table = by_name.get(name)
        if not table:
            continue
        for key in table.foreign_keys:
            if key.ref_table in tables:
                sig = (name, key.field, key.ref_table, key.ref_field)
                if sig not in have:
                    joins.append(Join(*sig))
                    have.add(sig)
    return tuple(joins)


def _column_expr(c: QueryColumn) -> str:
    return f"{quote(c.table)}.{quote(c.field)}"


def _aggregate(c: QueryColumn) -> str:
    base = _column_expr(c)
    return {"sum": f"SUM({base})", "avg": f"AVG({base})", "min": f"MIN({base})",
            "max": f"MAX({base})", "count": f"COUNT({base})"}.get(c.total, base)


def _default_alias(c: QueryColumn) -> str:
    names = {"sum": "Sum of", "avg": "Average of", "min": "Min of", "max": "Max of",
             "count": "Count of"}
    return f"{names[c.total]} {c.field}" if c.total in names else c.field


def to_sql(design: QueryDesign, schema: list[Table]) -> str:
    """The SELECT for a design. Raises QueryError if it can't be built."""
    if not design.tables:
        raise QueryError("Add a table to the query.")
    if not design.columns:
        raise QueryError("Add at least one field to the query.")
    by_name = {t.name: t for t in schema}
    for c in design.columns:
        if c.table not in design.tables:
            raise QueryError("A field belongs to a table that isn't in the query.")
        table = by_name.get(c.table)
        if table is None or table.field(c.field) is None:
            raise QueryError("A field in the query no longer exists.")
        if c.total not in TOTALS or c.sort not in SORTS:
            raise QueryError("The query has an option Folio doesn't know.")
    aggregated = any(c.total not in ("", "group") for c in design.columns)

    select, group_by, where_and, where_or, having, order = [], [], [], [], [], []
    for c in design.columns:
        ftype = by_name[c.table].field(c.field).type
        is_total = c.total not in ("", "group")
        expr = _aggregate(c) if is_total else _column_expr(c)
        if c.show:
            alias = c.alias or (_default_alias(c) if is_total else "")
            select.append(expr + (f" AS {quote(alias)}" if alias else ""))
        if aggregated and not is_total and (c.show or c.criteria or c.or_criteria):
            group_by.append(_column_expr(c))
        cond = criterion_sql(expr, c.criteria, ftype.INTEGER if c.total == "count" else ftype)
        alt = criterion_sql(expr, c.or_criteria, ftype.INTEGER if c.total == "count" else ftype)
        if cond:
            (having if is_total else where_and).append(cond)
        if alt:
            (having if is_total else where_or).append(alt)
        if c.sort:
            order.append(f"{expr} {c.sort.upper()}")
    if not select:
        raise QueryError("Show at least one field.")

    parts = ["SELECT " + ("DISTINCT " if design.distinct else "") + ", ".join(select)]
    first, *rest = design.tables
    parts.append(f"FROM {quote(first)}")
    joined = {first}
    for name in rest:
        join = next((j for j in design.joins
                     if (j.left_table in joined and j.right_table == name)
                     or (j.right_table in joined and j.left_table == name)), None)
        if join is None:
            parts.append(f"CROSS JOIN {quote(name)}")
        else:
            kind = "LEFT JOIN" if join.kind == "left" else "INNER JOIN"
            parts.append(f"{kind} {quote(name)} ON {quote(join.left_table)}.{quote(join.left_field)}"
                         f" = {quote(join.right_table)}.{quote(join.right_field)}")
        joined.add(name)
    if where_and or where_or:
        conds = []
        if where_and:
            conds.append(" AND ".join(where_and))
        if where_or:
            conds.append(" AND ".join(where_or))
        parts.append("WHERE " + (conds[0] if len(conds) == 1 else " OR ".join(f"({c})" for c in conds)))
    if group_by:
        parts.append("GROUP BY " + ", ".join(dict.fromkeys(group_by)))
    if having:
        parts.append("HAVING " + " AND ".join(having))
    if order:
        parts.append("ORDER BY " + ", ".join(order))
    return "\n".join(parts)


# ---- saving -------------------------------------------------------------------------

def design_to_dict(d: QueryDesign) -> dict:
    return {
        "tables": list(d.tables), "distinct": d.distinct,
        "joins": [vars(j) | {} for j in d.joins],
        "columns": [vars(c) | {} for c in d.columns],
    }


def design_from_dict(data: dict) -> QueryDesign:
    return QueryDesign(
        tables=tuple(data.get("tables", ())),
        joins=tuple(Join(**j) for j in data.get("joins", ())),
        columns=tuple(QueryColumn(**c) for c in data.get("columns", ())),
        distinct=bool(data.get("distinct", False)),
    )

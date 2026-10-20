import sqlite3

import pytest

from folio.domain.objects import ReportDef, build_report
from folio.domain.query import (Join, QueryColumn, QueryDesign, QueryError, auto_joins,
                                criterion_sql, design_from_dict, design_to_dict, to_sql)
from folio.domain.schema import (Field, FieldType, ForeignKey, SchemaError, Table,
                                 create_table_sql)
from folio.domain.values import InvalidValueError, coerce, guess_type

T, I, N = FieldType.TEXT, FieldType.INTEGER, FieldType.NUMBER


def schema():
    return [
        Table("Customers", (Field("id", I, primary_key=True, autonumber=True),
                            Field("name", T, required=True), Field("city", T))),
        Table("Orders", (Field("id", I, primary_key=True, autonumber=True),
                         Field("customer", I), Field("total", N), Field("placed", FieldType.DATE)),
              (ForeignKey("customer", "Customers", "id"),)),
    ]


def run(sql, db=None):
    db = db or sqlite3.connect(":memory:")
    for t in schema():
        db.execute(create_table_sql(t))
    db.executemany("INSERT INTO Customers(name, city) VALUES (?,?)",
                   [("Ada", "Rome"), ("Bob", "Milan"), ("Cy", "Rome")])
    db.executemany("INSERT INTO Orders(customer,total,placed) VALUES (?,?,?)",
                   [(1, 10, "2026-01-05"), (1, 30, "2026-02-01"), (2, 5, "2026-03-09")])
    return db.execute(sql).fetchall()


@pytest.mark.parametrize("text, ftype, expected", [
    ("12", I, 12), ("12.0", I, 12), (" ", I, None), ("3,5", N, 3.5), ("1,234.5", N, 1234.5),
    ("yes", FieldType.YES_NO, 1), ("No", FieldType.YES_NO, 0),
    ("20/10/2026", FieldType.DATE, "2026-10-20"),
    ("2026-10-20 14:30", FieldType.DATETIME, "2026-10-20 14:30:00"),
    ("", T, None), ("hi", T, "hi"),
])
def test_coerce(text, ftype, expected):
    assert coerce(text, ftype) == expected


@pytest.mark.parametrize("text, ftype", [("1.5", I), ("abc", N), ("maybe", FieldType.YES_NO),
                                        ("31/02/2026", FieldType.DATE)])
def test_coerce_rejects(text, ftype):
    with pytest.raises(InvalidValueError):
        coerce(text, ftype)


def test_guess_type():
    assert guess_type(["1", "2", ""]) is I
    assert guess_type(["007", "12"]) is T  # zip codes keep their zeros
    assert guess_type(["1.5", "2"]) is N
    assert guess_type(["2026-01-02", "2026-02-03"]) is FieldType.DATE
    assert guess_type(["yes", "no"]) is FieldType.YES_NO
    assert guess_type([]) is T


def test_create_table_round_trips_in_sqlite():
    sql = create_table_sql(schema()[1])
    assert "FOREIGN KEY" in sql and "AUTOINCREMENT" in sql
    sqlite3.connect(":memory:").execute(sql)


def test_invalid_designs():
    with pytest.raises(SchemaError):
        create_table_sql(Table("x", ()))
    with pytest.raises(SchemaError):
        create_table_sql(Table("x", (Field("a"), Field("A"))))
    with pytest.raises(SchemaError):
        create_table_sql(Table("x", (Field("a", T, autonumber=True, primary_key=True),)))
    with pytest.raises(SchemaError):
        create_table_sql(Table("x", (Field("a", I, default="abc"),)))


@pytest.mark.parametrize("text, ftype, rows", [
    (">= 10", N, 2), ("5 or 10", N, 2), ("between 5 and 10", N, 2), ("> 5 and < 30", N, 1),
    ("in (5, 30)", N, 2), ("not 5", N, 2), ("is null", N, 0),
])
def test_criteria_numbers(text, ftype, rows):
    where = criterion_sql('"total"', text, ftype)
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE o (total REAL)")
    db.executemany("INSERT INTO o VALUES (?)", [(10,), (30,), (5,)])
    assert len(db.execute(f'SELECT 1 FROM o WHERE {where.replace(chr(34) + "total" + chr(34), "total")}').fetchall()) == rows


@pytest.mark.parametrize("text, count", [
    ("rome", 2), ("R*", 2), ("like \"*ilan\"", 1), ('"Rome" or "Milan"', 3), ("<> Rome", 1),
    ("not like R*", 1),
])
def test_criteria_text(text, count):
    where = criterion_sql('"city"', text, T)
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE c (city TEXT)")
    db.executemany("INSERT INTO c VALUES (?)", [("Rome",), ("Milan",), ("Rome",)])
    assert len(db.execute(f"SELECT 1 FROM c WHERE {where.replace(chr(34) + 'city' + chr(34), 'city')}").fetchall()) == count


def test_criteria_cannot_inject():
    where = criterion_sql('"city"', "x'; DROP TABLE c; --", T)
    assert "''" in where and where.count("'") % 2 == 0


def test_criteria_errors():
    with pytest.raises(QueryError):
        criterion_sql('"n"', "abc", I)
    with pytest.raises(QueryError):
        criterion_sql('"n"', ">", I)


def test_query_with_join_sort_and_criteria():
    design = QueryDesign(
        ("Customers", "Orders"), auto_joins(["Customers", "Orders"], schema()),
        (QueryColumn("Customers", "name", sort="asc"),
         QueryColumn("Orders", "total", criteria=">= 10")))
    assert run(to_sql(design, schema())) == [("Ada", 10.0), ("Ada", 30.0)]


def test_query_totals_group_by():
    design = QueryDesign(
        ("Customers", "Orders"), auto_joins(["Customers", "Orders"], schema()),
        (QueryColumn("Customers", "name"), QueryColumn("Orders", "total", total="sum", sort="desc")))
    assert run(to_sql(design, schema())) == [("Ada", 40.0), ("Bob", 5.0)]


def test_left_join_keeps_customers_without_orders():
    joins = (Join("Orders", "customer", "Customers", "id", "left"),)
    design = QueryDesign(("Orders", "Customers"), joins,
                         (QueryColumn("Customers", "name"),), distinct=True)
    assert len(run(to_sql(design, schema()))) == 2  # Cy has no orders; Orders is the left table
    design = QueryDesign(("Customers", "Orders"), (Join("Customers", "id", "Orders", "customer", "left"),),
                         (QueryColumn("Customers", "name"),), distinct=True)
    assert len(run(to_sql(design, schema()))) == 3


def test_or_criteria_row():
    design = QueryDesign(("Customers",), (), (QueryColumn("Customers", "city", criteria="Milan",
                                                          or_criteria="Rome"),))
    assert len(run(to_sql(design, schema()))) == 3


def test_query_errors_and_round_trip():
    with pytest.raises(QueryError):
        to_sql(QueryDesign(), schema())
    with pytest.raises(QueryError):
        to_sql(QueryDesign(("Customers",), (), (QueryColumn("Customers", "nope"),)), schema())
    design = QueryDesign(("Customers",), (), (QueryColumn("Customers", "name", sort="asc"),), True)
    assert design_from_dict(design_to_dict(design)) == design


def test_report_groups_and_totals():
    rows = [("Rome", "Ada", 10), ("Milan", "Bob", 5), ("Rome", "Cy", 7), (None, "Dee", 1)]
    data = build_report(ReportDef("t", columns=("name", "n"), group_by="city", sort_by="name",
                                  sum_columns=("n",)), ["city", "name", "n"], rows)
    assert [g.key for g in data.groups] == ["Milan", "Rome", None]
    assert data.groups[1].rows == (("Ada", 10), ("Cy", 7))
    assert data.groups[1].sums == (None, 17)
    assert data.totals == (None, 23) and data.row_count == 4


def test_report_without_group():
    data = build_report(ReportDef("t", sort_by="n", descending=True), ["a", "n"], [("x", 1), ("y", 2)])
    assert [r[0] for r in data.groups[0].rows] == ["y", "x"]

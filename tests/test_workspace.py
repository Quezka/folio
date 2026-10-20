import sqlite3

import pytest

from folio.application.errors import (ConstraintError, DesignError, FileFormatError,
                                      IncompleteRowError, NotOpenError)
from folio.application.inputs import (FieldDesign, FormDef, ImportField, ImportSpec, QueryColumn,
                                      QueryDesign, ReportDef, TableDesign)
from folio.application.ports import (AccessColumn, AccessDatabase, AccessLink, AccessTable,
                                      RowQuery)
from folio.application.types import FieldType
from folio.application.workspace import Change, Source

T, I, N = FieldType.TEXT, FieldType.INTEGER, FieldType.NUMBER


def key():
    return FieldDesign("id", I, True, True)


@pytest.fixture
def shop(ws):
    ws.save_table(None, TableDesign("Customers", (key(), FieldDesign("name", T, required=True),
                                                  FieldDesign("city", T))))
    ws.save_table(None, TableDesign("Orders", (
        key(), FieldDesign("customer", I, ref_table="Customers", ref_field="id"),
        FieldDesign("total", N), FieldDesign("placed", FieldType.DATE))))
    return ws


def rows(ws, table, **kw):
    return [r.values for r in ws.page(Source("table", table), RowQuery(**kw)).rows]


def test_a_new_database_is_empty_and_remembered(ws):
    assert ws.tables() == [] and ws.is_open and ws.name == "test"
    assert ws.recent() == [ws.path]


def test_nothing_works_without_a_database(tmp_path):
    from folio.bootstrap import build_services
    from folio.infrastructure.settings import MemorySettings
    closed = build_services(settings=MemorySettings()).workspace
    with pytest.raises(NotOpenError):
        closed.tables()


def test_opening_a_file_that_isnt_a_database_is_refused(tmp_path):
    from folio.bootstrap import build_services
    from folio.infrastructure.settings import MemorySettings
    bad = tmp_path / "x.folio"
    bad.write_text("hello, this is not sqlite at all")
    with pytest.raises(FileFormatError):
        build_services(settings=MemorySettings()).workspace.open(str(bad))


def test_any_sqlite_file_opens(tmp_path, ws):
    other = tmp_path / "plain.db"
    db = sqlite3.connect(other)
    db.execute("CREATE TABLE pets (id INTEGER PRIMARY KEY, name TEXT NOT NULL, born DATE, "
               "owner_id INTEGER REFERENCES pets(id))")
    db.execute("INSERT INTO pets (name) VALUES ('Rex')")
    db.commit()
    db.close()
    ws.open(str(other))
    table = ws.table("pets")
    assert [f.name for f in table.fields] == ["id", "name", "born", "owner_id"]
    assert table.field("name").required and table.field("born").type is FieldType.DATE
    assert table.field("owner_id").ref_table == "pets"
    assert table.row_count == 1 and not table.locked


def test_cells_are_typed_and_validated(shop):
    c = shop.insert_row("Customers", {"name": "Ada", "city": "Rome"})
    shop.insert_row("Orders", {"customer": str(c), "total": "3,5", "placed": "20/10/2026"})
    assert rows(shop, "Orders") == [(1, 1, 3.5, "2026-10-20")]
    with pytest.raises(DesignError):
        shop.update_cell("Orders", 1, "total", "lots")
    with pytest.raises(DesignError):
        shop.update_cell("Orders", 1, "placed", "31/02/2026")


def test_required_unique_and_links_are_enforced(shop):
    with pytest.raises(IncompleteRowError):
        shop.insert_row("Customers", {"city": "Rome"})
    with pytest.raises(ConstraintError):
        shop.insert_row("Orders", {"customer": "99"})  # no such customer
    c = shop.insert_row("Customers", {"name": "Ada"})
    shop.insert_row("Orders", {"customer": str(c)})
    with pytest.raises(ConstraintError):
        shop.delete_rows("Customers", [c])  # an order still points at it
    assert rows(shop, "Customers") == [(1, "Ada", None)]


def test_undo_and_redo_of_edits_inserts_and_deletes(shop):
    c = shop.insert_row("Customers", {"name": "Ada"})
    shop.update_cell("Customers", c, "name", "Bea")
    shop.delete_rows("Customers", [c])
    assert rows(shop, "Customers") == []
    assert shop.undo() and rows(shop, "Customers") == [(1, "Bea", None)]  # the deleted row is back
    assert shop.undo() and rows(shop, "Customers") == [(1, "Ada", None)]
    assert shop.undo() and rows(shop, "Customers") == []
    assert not shop.undo()
    assert shop.redo() and shop.redo() and shop.redo()
    assert rows(shop, "Customers") == []
    assert not shop.redo()


def test_undoing_a_delete_restores_the_same_ids(shop):
    for n in ("a", "b", "c"):
        shop.insert_row("Customers", {"name": n})
    shop.delete_rows("Customers", [2])
    shop.undo()
    assert [r[0] for r in rows(shop, "Customers")] == [1, 2, 3]


def test_search_filter_sort_and_paging(shop):
    for i in range(450):
        shop.insert_row("Customers", {"name": f"n{i:03}", "city": "Rome" if i % 3 == 0 else "Milan"})
    page = shop.page(Source("table", "Customers"), RowQuery(), 0, 200)
    assert page.total == 450 and len(page.rows) == 200
    assert shop.page(Source("table", "Customers"), RowQuery(), 400, 200).rows[-1].values[1] == "n449"
    assert shop.page(Source("table", "Customers"), RowQuery(search="n44"), 0, 50).total == 10
    assert shop.page(Source("table", "Customers"), RowQuery(filters=(("city", "=", "Rome"),)), 0, 5).total == 150
    first = shop.page(Source("table", "Customers"), RowQuery(order_by="name", descending=True), 0, 1)
    assert first.rows[0].values[1] == "n449"
    assert shop.page(Source("table", "Customers"), RowQuery(search="100%"), 0, 5).total == 0  # % is literal


def test_changing_a_design_keeps_the_rows(shop):
    c = shop.insert_row("Customers", {"name": "Ada", "city": "Rome"})
    shop.insert_row("Orders", {"customer": str(c), "total": "10"})
    shop.save_table("Customers", TableDesign("Clients", (
        FieldDesign("id", I, True, True, original_name="id"),
        FieldDesign("full_name", T, required=True, original_name="name"),
        FieldDesign("city", T, original_name="city"), FieldDesign("vip", FieldType.YES_NO))))
    assert [t.name for t in shop.tables()] == ["Clients", "Orders"]
    assert rows(shop, "Clients") == [(1, "Ada", "Rome", None)]
    assert shop.table("Orders").field("customer").ref_table == "Clients"  # the link followed the rename
    shop.insert_row("Orders", {"customer": "1"})


def test_design_mistakes_are_explained(shop):
    with pytest.raises(DesignError):
        shop.save_table(None, TableDesign("customers", (key(),)))  # same name, other case
    with pytest.raises(DesignError):
        shop.save_table(None, TableDesign("Bad", (FieldDesign("a"), FieldDesign("a"))))
    with pytest.raises(DesignError):
        shop.save_table(None, TableDesign("Bad", (FieldDesign("a", ref_table="Customers", ref_field="city"),)))
    with pytest.raises(DesignError):  # Orders points at Customers.id
        shop.save_table("Customers", TableDesign("Customers", (FieldDesign("name", T, original_name="name"),)))
    with pytest.raises(DesignError):
        shop.drop_table("Customers")
    shop.drop_table("Orders")
    shop.drop_table("Customers")
    assert shop.tables() == []


def test_a_design_the_rows_dont_fit_is_refused_and_nothing_changes(shop):
    shop.insert_row("Customers", {"name": "Ada"})
    shop.insert_row("Customers", {"name": "Bea"})
    with pytest.raises(ConstraintError):
        shop.save_table("Customers", TableDesign("Customers", (
            FieldDesign("id", I, True, True, original_name="id"),
            FieldDesign("name", T, unique=True, required=True, original_name="name"),
            FieldDesign("city", T, required=True, original_name="city"))))  # city is empty
    assert [f.name for f in shop.table("Customers").fields] == ["id", "name", "city"]
    assert not shop.table("Customers").field("city").required
    assert len(rows(shop, "Customers")) == 2


def test_queries_are_saved_run_and_followed_by_forms(shop):
    c = shop.insert_row("Customers", {"name": "Ada", "city": "Rome"})
    shop.insert_row("Orders", {"customer": str(c), "total": "40"})
    shop.insert_row("Orders", {"customer": str(c), "total": "2"})
    design = QueryDesign(("Customers", "Orders"), shop.suggest_joins(["Customers", "Orders"]),
                         (QueryColumn("Customers", "name"), QueryColumn("Orders", "total", total="sum")))
    sql = shop.build_sql(design)
    shop.save_query("Totals", None, sql, design)
    assert shop.queries() == ["Totals"] and shop.query("Totals").design == design
    page = shop.page(Source("query", "Totals"))
    assert [c.name for c in page.columns] == ["name", "Sum of total"]
    assert page.rows[0].values == ("Ada", 42.0)
    shop.save_form("Totals form", None, shop.default_form(Source("query", "Totals")))
    shop.save_query("Sums", "Totals", sql, design)  # renaming a query moves the forms on it
    assert shop.form("Totals form").source == "Sums"
    with pytest.raises(DesignError):
        shop.save_query("Bad", None, "DELETE FROM Customers")
    with pytest.raises(DesignError):
        shop.save_query("Bad", None, "SELECT nope FROM Customers")


def test_forms_and_reports_follow_their_table(shop):
    shop.save_form("F", None, shop.default_form(Source("table", "Customers")))
    shop.save_report("R", None, ReportDef("Customers", columns=("name",)))
    shop.save_table("Customers", TableDesign("Clients", (
        FieldDesign("id", I, True, True, original_name="id"),
        FieldDesign("name", T, original_name="name"), FieldDesign("city", T, original_name="city"))))
    assert shop.form("F").source == "Clients" and shop.report("R").source == "Clients"
    shop.drop_table("Orders")
    shop.drop_table("Clients")
    assert shop.forms() == [] and shop.reports() == []


def test_report_shows_what_links_point_at(shop):
    a = shop.insert_row("Customers", {"name": "Ada"})
    b = shop.insert_row("Customers", {"name": "Bea"})
    for who, total in ((a, 10), (a, 5), (b, 1)):
        shop.insert_row("Orders", {"customer": str(who), "total": str(total)})
    view = shop.build_report(ReportDef("Orders", columns=("customer", "total"), group_by="customer",
                                       sum_columns=("total",)))
    assert [g.key for g in view.groups] == ["Ada", "Bea"]
    assert view.groups[0].sums == (None, 15) and view.totals == (None, 16)


def test_lookup_labels_use_the_first_text_field(shop):
    shop.insert_row("Customers", {"name": "Ada", "city": "Rome"})
    assert [(o.key, o.label) for o in shop.lookup("Customers")] == [(1, "Ada")]


def test_csv_import_guesses_types_and_export_round_trips(shop, tmp_path):
    src = tmp_path / "pets.csv"
    src.write_text("name;born;weight;chipped\nRex;2020-01-05;12,5;yes\nTom;07/03/2019;4;no\n", encoding="utf-8")
    preview = shop.preview_csv(str(src))
    assert preview.header == ("name", "born", "weight", "chipped") and preview.total_rows == 2
    assert preview.types == (T, FieldType.DATE, N, FieldType.YES_NO)
    fields = tuple(ImportField(h, t, i) for i, (h, t) in enumerate(zip(preview.header, preview.types)))
    result = shop.import_csv(ImportSpec(str(src), "Pets", fields))
    assert (result.rows, result.problems) == (2, 0)
    assert rows(shop, "Pets") == [(1, "Rex", "2020-01-05", 12.5, 1), (2, "Tom", "2019-03-07", 4.0, 0)]
    out = tmp_path / "out.csv"
    assert shop.export_csv(Source("table", "Pets"), str(out)) == 2
    assert out.read_text(encoding="utf-8-sig").splitlines()[0] == "id,name,born,weight,chipped"


def test_csv_import_counts_values_that_dont_fit_and_can_append(shop, tmp_path):
    src = tmp_path / "n.csv"
    src.write_text("n\n1\nx\n3\n", encoding="utf-8")
    result = shop.import_csv(ImportSpec(str(src), "Nums", (ImportField("n", I, 0),), add_key=False))
    assert result.problems == 1
    assert [r[0] for r in rows(shop, "Nums")] == [1, None, 3]
    shop.import_csv(ImportSpec(str(src), "Nums", (ImportField("n", I, 0),), append=True))
    assert len(rows(shop, "Nums")) == 6
    with pytest.raises(DesignError):
        shop.import_csv(ImportSpec(str(src), "Nums", (ImportField("n", I, 0),)))


def test_access_tables_are_converted(ws, access):
    A = AccessColumn
    access.database = AccessDatabase((
        AccessTable("Staff", (A("ID", "autonumber", key=True), A("Name", "text", required=True),
                              A("Hired", "date"), A("Pay", "number"), A("Active", "boolean"),
                              A("Notes", "longtext")),
                    ((1, "Ada", "2020-01-02", 1200.5, True, "x"), (2, "Bob", "2021-05-06", None, False, None)),
                    skipped=("Photo",)),
        AccessTable("Shifts", (A("Staff", "integer"), A("Day", "datetime")),
                    ((1, "2026-10-20 08:30:00"), (2, "2026-10-21 09:00:00")))),
        (AccessLink("Shifts", "Staff", "Staff", "ID", cascade=True),
         AccessLink("Shifts", "Day", "Nowhere", "id")))
    report = ws.import_access("x.accdb")
    assert [(r.table, r.rows) for r in report.tables] == [("Staff", 2), ("Shifts", 2)]
    assert (report.links, report.links_lost, report.skipped_columns) == (1, 1, 1)
    t = ws.table("Staff")
    assert [f.name for f in t.fields] == ["ID", "Name", "Hired", "Pay", "Active", "Notes"]
    assert [f.type for f in t.fields] == [I, T, FieldType.DATE, N, FieldType.YES_NO, FieldType.LONG_TEXT]
    assert t.field("ID").autonumber and t.field("Name").required
    assert rows(ws, "Staff")[0] == (1, "Ada", "2020-01-02", 1200.5, 1, "x")
    shifts = ws.table("Shifts")
    assert shifts.field("Staff").ref_table == "Staff" and shifts.field("Staff").on_delete == "CASCADE"
    assert shifts.field("Day").type is FieldType.DATETIME


def test_a_database_is_exported_for_access(shop, access, tmp_path):
    c = shop.insert_row("Customers", {"name": "Ada", "city": "Rome"})
    shop.insert_row("Orders", {"customer": str(c), "total": "2,5", "placed": "2026-10-20"})
    long_text = "x" * 300
    shop.insert_row("Customers", {"name": long_text})
    report = shop.export_access(str(tmp_path / "out.accdb"))
    assert (report.tables, report.rows, report.links) == (2, 3, 1)
    path, db = access.written[0]
    assert path.endswith("out.accdb")
    customers = next(t for t in db.tables if t.name == "Customers")
    assert [(c.name, c.kind, c.key, c.required) for c in customers.columns] == [
        ("id", "autonumber", True, False), ("name", "longtext", False, True), ("city", "text", False, False)]
    orders = next(t for t in db.tables if t.name == "Orders")
    assert orders.rows == ((1, 1, 2.5, "2026-10-20"),)
    assert [(k.child, k.child_field, k.parent) for k in db.links] == [("Orders", "customer", "Customers")]


def test_the_relationships_layout_is_kept(shop):
    shop.save_layout({"Orders": [10, 20]})
    assert shop.layout() == {"Orders": [10, 20]}
    assert [(r.child, r.parent) for r in shop.relationships()] == [("Orders", "Customers")]


def test_changes_are_announced(shop):
    seen = []
    shop.subscribe(seen.append)
    shop.insert_row("Customers", {"name": "Ada"})
    shop.save_query("Q", None, "SELECT 1")
    shop.save_table("Customers", TableDesign("Customers", (
        FieldDesign("id", I, True, True, original_name="id"), FieldDesign("name", T, original_name="name"))))
    assert seen == [Change.DATA, Change.OBJECTS, Change.SCHEMA]


def test_a_money_field_survives_a_design_change_and_import(shop, tmp_path):
    shop.save_table("Orders", TableDesign("Orders", (
        FieldDesign("id", I, True, True, original_name="id"),
        FieldDesign("customer", I, ref_table="Customers", ref_field="id", original_name="customer"),
        FieldDesign("total", FieldType.CURRENCY, currency="GBP", original_name="total"))))
    assert shop.table("Orders").field("total").type is FieldType.CURRENCY
    assert shop.table("Orders").field("total").currency == "GBP"
    src = tmp_path / "m.csv"
    src.write_text("item;price\nPen;€ 1,50\nBook;€ 12,00\n", encoding="utf-8")
    preview = shop.preview_csv(str(src))
    assert preview.types[1] is FieldType.CURRENCY and preview.currencies[1] == "EUR"
    shop.import_csv(ImportSpec(str(src), "Items", tuple(
        ImportField(h, t, i, c) for i, (h, t, c) in enumerate(zip(preview.header, preview.types, preview.currencies)))))
    assert shop.table("Items").field("price").currency == "EUR"
    assert rows(shop, "Items") == [(1, "Pen", 1.5), (2, "Book", 12.0)]


def test_query_results_keep_money_and_dates_typed(shop):
    c = shop.insert_row("Customers", {"name": "Ada"})
    shop.insert_row("Orders", {"customer": str(c), "total": "5"})
    shop.save_table("Orders", TableDesign("Orders", (
        FieldDesign("id", I, True, True, original_name="id"),
        FieldDesign("customer", I, ref_table="Customers", ref_field="id", original_name="customer"),
        FieldDesign("total", FieldType.CURRENCY, original_name="total"))))
    design = QueryDesign(("Orders",), (), (QueryColumn("Orders", "total", total="sum"),))
    shop.save_query("T", None, shop.build_sql(design), design)
    column = shop.page(Source("query", "T")).columns[0]
    assert column.type is FieldType.CURRENCY and column.currency == "EUR"


def test_access_links_the_file_never_declared_are_inferred(ws, access):
    A = AccessColumn
    access.database = AccessDatabase((
        AccessTable("Catene", (A("ID", "autonumber", key=True), A("Nome", "text")), ((1, "A"), (2, "B"))),
        AccessTable("Negozi", (A("ID", "autonumber", key=True), A("Citta", "text"), A("ID_Catena", "integer")),
                    ((1, "Milano", 1), (2, "Roma", 1), (3, "Bari", 2))),
        AccessTable("Persone", (A("CF", "text", key=True), A("Salario", "currency", currency="EUR")),
                    (("X1", 2500.0), ("X2", 2800.5))),
        AccessTable("Dipendenti", (A("ID_Negozio", "integer", key=True), A("CF", "text", key=True)),
                    ((1, "X1"), (2, "X2"))),
        AccessTable("Numeri", (A("ID", "autonumber", key=True), A("Valore", "integer")), ((1, 1), (2, 2)))))
    report = ws.import_access("x.accdb")
    assert report.links_inferred == 3
    assert {(r.child, r.child_field, r.parent) for r in ws.relationships()} == {
        ("Negozi", "ID_Catena", "Catene"), ("Dipendenti", "ID_Negozio", "Negozi"),
        ("Dipendenti", "CF", "Persone")}  # Catene.ID does not "point at" Negozi just because 1,2 ⊂ 1,2,3
    assert ws.table("Persone").field("Salario").type is FieldType.CURRENCY

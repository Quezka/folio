"""Editing Access files in place, through the real helper (skipped without Java)."""
import shutil
import sys
import subprocess
from pathlib import Path

import pytest

from folio.application.errors import ConstraintError, DesignError, FileAccessError
from folio.application.inputs import (FieldDesign, QueryColumn, QueryDesign, ReportDef,
                                      TableDesign)
from folio.application.ports import RowQuery
from folio.application.types import FieldType
from folio.application.workspace import Source, Workspace
from folio.infrastructure.access_files import AccessFilesAdapter, find_java
from folio.infrastructure.access_native import AccessBackedDatabase, DatabaseRouter
from folio.infrastructure.csv_files import CsvFilesAdapter
from folio.infrastructure.settings import MemorySettings

ROOT = Path(__file__).resolve().parent.parent
T, I = FieldType.TEXT, FieldType.INTEGER


@pytest.fixture(scope="module")
def jar():
    if find_java() is None:
        pytest.skip("no Java runtime")
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import build_java
        return build_java.build_jar()
    except (SystemExit, OSError, subprocess.CalledProcessError) as e:
        pytest.skip(f"can't build the Access helper: {e}")
    finally:
        sys.path.remove(str(ROOT / "scripts"))


@pytest.fixture
def make(jar, tmp_path):
    opened = []

    def factory():
        adapter = AccessFilesAdapter(jar=jar)
        ws = Workspace(DatabaseRouter(access=AccessBackedDatabase(adapter)), CsvFilesAdapter(),
                       adapter, MemorySettings())
        opened.append(ws)
        return ws

    yield factory
    for ws in opened:
        ws.close()


def key():
    return FieldDesign("id", I, True, True)


def rows(ws, table, **kw):
    return [r.values for r in ws.page(Source("table", table), RowQuery(order_by="id", **kw), 0, 500).rows]


@pytest.fixture
def shop(make, tmp_path):
    """A new .accdb with two linked tables."""
    ws = make()
    ws.create(str(tmp_path / "shop.accdb"))
    ws.save_table(None, TableDesign("Customers", (key(), FieldDesign("name", T, required=True),
                                                  FieldDesign("balance", FieldType.CURRENCY, currency="EUR"))))
    ws.save_table(None, TableDesign("Orders", (
        key(), FieldDesign("customer", I, ref_table="Customers", ref_field="id"),
        FieldDesign("placed", FieldType.DATE), FieldDesign("paid", FieldType.YES_NO))))
    return ws


def reopen(make, ws):
    path = ws.path
    ws.close()
    fresh = make()
    fresh.open(path)
    return fresh


def test_a_new_access_file_is_created_and_filled_natively(shop, make):
    assert shop.is_access and shop.path.endswith("shop.accdb")
    c = shop.insert_row("Customers", {"name": "Ada Łovelace", "balance": "€ 1.234,50"})
    shop.insert_row("Orders", {"customer": str(c), "placed": "20/10/2026", "paid": "yes"})
    again = reopen(make, shop)
    assert rows(again, "Customers") == [(1, "Ada Łovelace", 1234.5)]
    assert rows(again, "Orders") == [(1, 1, "2026-10-20", 1)]
    assert again.table("Customers").field("balance").type is FieldType.CURRENCY
    assert [(r.child, r.parent) for r in again.relationships()] == [("Orders", "Customers")]


def test_edits_undo_and_deletes_reach_the_file(shop, make):
    for n in ("a", "b", "c"):
        shop.insert_row("Customers", {"name": n})
    shop.update_cell("Customers", 2, "name", "B!")
    shop.delete_rows("Customers", [3])
    shop.undo()  # c comes back
    shop.update_cell("Customers", 1, "balance", "10")
    again = reopen(make, shop)
    assert rows(again, "Customers") == [(1, "a", 10.0), (2, "B!", None), (3, "c", None)]


def test_autonumbers_stay_in_step_with_access(shop, make):
    for n in ("a", "b", "c"):
        shop.insert_row("Customers", {"name": n})
    shop.delete_rows("Customers", [3])
    new = shop.insert_row("Customers", {"name": "d"})  # Access never reuses 3
    assert new == 4 and rows(shop, "Customers")[-1][:2] == (4, "d")
    again = reopen(make, shop)
    assert [r[0] for r in rows(again, "Customers")] == [1, 2, 4]


def test_access_refusing_a_change_leaves_nothing_half_done(shop, make):
    shop.insert_row("Customers", {"name": "ok"})
    with pytest.raises(DesignError):
        shop.update_cell("Customers", 1, "name", "x" * 300)  # an Access text field holds 255
    assert rows(shop, "Customers") == [(1, "ok", None)]
    with pytest.raises(DesignError):
        shop.insert_row("Customers", {"name": "y" * 300})
    assert len(rows(shop, "Customers")) == 1
    assert len(rows(reopen(make, shop), "Customers")) == 1


def test_fields_and_links_can_be_added_but_nothing_existing_changed(shop, make):
    shop.insert_row("Customers", {"name": "Ada"})
    design = TableDesign("Customers", (
        FieldDesign("id", I, True, True, original_name="id"),
        FieldDesign("name", T, required=True, original_name="name"),
        FieldDesign("balance", FieldType.CURRENCY, currency="EUR", original_name="balance"),
        FieldDesign("city", T), FieldDesign("vip", FieldType.YES_NO)))
    shop.save_table("Customers", design)
    shop.update_cell("Customers", 1, "city", "Rome")
    again = reopen(make, shop)
    assert [f.name for f in again.table("Customers").fields] == ["id", "name", "balance", "city", "vip"]
    assert rows(again, "Customers") == [(1, "Ada", None, "Rome", 0)]  # Access: Yes/No is never empty
    # a rename, a removal, a new type and a new table link target are all refused …
    for bad in (
            TableDesign("Customers", (FieldDesign("id", I, True, True, original_name="id"),
                                      FieldDesign("full_name", T, required=True, original_name="name"),
                                      *design.fields[2:])),
            TableDesign("Customers", design.fields[:3]),
            TableDesign("Customers", (design.fields[0], FieldDesign("name", I, required=True, original_name="name"),
                                      *design.fields[2:])),
            TableDesign("Clients", design.fields)):
        with pytest.raises(DesignError):
            again.save_table("Customers", bad)
    with pytest.raises(DesignError):
        again.drop_table("Orders")
    with pytest.raises(DesignError):
        again.compact()
    # … but a new table and a new link are fine
    again.save_table(None, TableDesign("Notes", (key(), FieldDesign("customer", I), FieldDesign("text", FieldType.LONG_TEXT))))
    orders = again.table("Notes")
    again.save_table("Notes", TableDesign("Notes", (
        FieldDesign("id", I, True, True, original_name="id"),
        FieldDesign("customer", I, ref_table="Customers", ref_field="id", original_name="customer"),
        FieldDesign("text", FieldType.LONG_TEXT, original_name="text"))))
    final = reopen(make, again)
    assert {(r.child, r.parent) for r in final.relationships()} == {("Orders", "Customers"), ("Notes", "Customers")}


def test_saved_queries_forms_and_reports_live_inside_the_file(shop, make):
    c = shop.insert_row("Customers", {"name": "Ada", "balance": "5"})
    shop.insert_row("Orders", {"customer": str(c)})
    design = QueryDesign(("Customers", "Orders"), shop.suggest_joins(["Customers", "Orders"]),
                         (QueryColumn("Customers", "name"), QueryColumn("Customers", "balance", total="sum")))
    shop.save_query("Totals", None, shop.build_sql(design), design)
    shop.save_form("Customer", None, shop.default_form(Source("table", "Customers")))
    shop.save_report("R", None, ReportDef("Customers", columns=("name", "balance"), sum_columns=("balance",)))
    shop.save_query("Totals2", "Totals", shop.query("Totals").sql, design)  # a rename
    again = reopen(make, shop)
    assert again.queries() == ["Totals2"] and again.forms() == ["Customer"] and again.reports() == ["R"]
    assert again.page(Source("query", "Totals2")).rows[0].values == ("Ada", 5.0)
    # those hidden objects never show up as tables
    assert [t.name for t in again.tables()] == ["Customers", "Orders"]
    again.delete_report("R")
    assert reopen(make, again).reports() == []


def test_a_table_without_a_key_can_still_be_edited(shop, make):
    shop.save_table(None, TableDesign("Log", (FieldDesign("what", T), FieldDesign("n", I))))
    for what, n in (("a", 1), ("b", 2), ("a", 3)):
        shop.insert_row("Log", {"what": what, "n": str(n)})
    page = shop.page(Source("table", "Log"))
    shop.update_cell("Log", page.rows[1].key, "what", "B")
    shop.delete_rows("Log", [page.rows[0].key])
    got = sorted(r.values for r in reopen(make, shop).page(Source("table", "Log")).rows)
    assert got == [("B", 2), ("a", 3)]


def test_csv_can_be_imported_into_an_access_file(shop, make, tmp_path):
    from folio.application.inputs import ImportField, ImportSpec
    src = tmp_path / "x.csv"
    src.write_text("name;price\nPen;€ 1,50\nBook;€ 12,00\n", encoding="utf-8")
    shop.import_csv(ImportSpec(str(src), "Items", (ImportField("name", T, 0), ImportField("price", FieldType.CURRENCY, 1, "EUR"))))
    again = reopen(make, shop)
    assert rows(again, "Items") == [(1, "Pen", 1.5), (2, "Book", 12.0)]
    assert again.table("Items").field("price").currency == "EUR"


def test_a_file_open_in_access_is_not_touched(make, shop, tmp_path):
    path = shop.path
    shop.close()
    Path(path).with_suffix(".laccdb").write_bytes(b"lock")
    with pytest.raises(FileAccessError, match="open in Microsoft Access"):
        make().open(path)


def test_the_file_is_backed_up_once_before_the_first_change(make, shop, tmp_path):
    path = Path(shop.path)
    shop.close()
    ws = make()
    ws.open(str(path))
    backup = path.with_name("shop.folio-backup.accdb")
    backup.unlink(missing_ok=True)  # (building the test file made one)
    assert not backup.exists()  # just looking changes nothing
    before = path.read_bytes()
    ws.insert_row("Customers", {"name": "x"})
    assert backup.read_bytes() == before and path.read_bytes() != before
    ws.insert_row("Customers", {"name": "y"})
    assert backup.read_bytes() == before  # still the original


def test_the_real_exercise_file_opens_edits_and_saves(make, tmp_path):
    source = Path.home() / "Downloads" / "CatenaNegozi_Domashenko.accdb"
    if not source.exists():
        pytest.skip("the exercise file isn't here")
    copy = tmp_path / "c.accdb"
    shutil.copy(source, copy)
    ws = make()
    ws.open(str(copy))
    assert ws.table_names() == ["Catene", "Dipendenti", "Negozi", "Persone", "Responsabili"]
    salary = ws.table("Persone").field("Salario")
    assert salary.type is FieldType.CURRENCY and salary.currency == "EUR"
    ws.update_cell("Persone", 1, "Salario", "€ 2.600,50")
    assert reopen(make, ws).page(Source("table", "Persone")).rows[0].values[5] == 2600.5

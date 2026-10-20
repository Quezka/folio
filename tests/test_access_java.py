"""Access files through the real Java helper (skipped when Java or the jars aren't available)."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from folio.application.errors import FileAccessError, FileFormatError
from folio.application.ports import AccessColumn, AccessDatabase, AccessLink, AccessTable, RowQuery
from folio.application.workspace import Source, Workspace
from folio.demo import build_library
from folio.infrastructure.access_files import AccessFilesAdapter, find_java
from folio.infrastructure.csv_files import CsvFilesAdapter
from folio.infrastructure.settings import MemorySettings
from folio.infrastructure.sqlite import SqliteDatabase

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def adapter():
    if find_java() is None:
        pytest.skip("no Java runtime")
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import build_java
        jar = build_java.build_jar()
    except (SystemExit, OSError, subprocess.CalledProcessError) as e:  # offline, no compiler…
        pytest.skip(f"can't build the Access helper: {e}")
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    return AccessFilesAdapter(jar=jar)


def make(tmp_path, adapter, name):
    ws = Workspace(SqliteDatabase(), CsvFilesAdapter(), adapter, MemorySettings())
    ws.create(str(tmp_path / name))
    return ws


def rows(ws, table):
    return [r.values for r in ws.page(Source("table", table), RowQuery(order_by="id"), 0, 1000).rows]


@pytest.mark.parametrize("extension", [".accdb", ".mdb"])
def test_a_database_survives_a_trip_through_access(adapter, tmp_path, extension):
    source = make(tmp_path, adapter, "a.folio")
    build_library(source)
    target = tmp_path / f"library{extension}"
    report = source.export_access(str(target))
    assert (report.tables, report.links) == (4, 3) and target.stat().st_size > 10_000

    copy = make(tmp_path, adapter, "b.folio")
    imported = copy.import_access(str(target))
    assert (imported.links, imported.links_lost, imported.skipped_columns) == (3, 0, 0)
    assert copy.table_names() == source.table_names()
    for name in source.table_names():
        assert [(f.name, f.type, f.primary_key, f.required) for f in copy.table(name).fields] == \
               [(f.name, f.type, f.primary_key, f.required) for f in source.table(name).fields]
        assert rows(copy, name) == rows(source, name)
    assert {(r.child, r.child_field, r.parent) for r in copy.relationships()} == \
           {(r.child, r.child_field, r.parent) for r in source.relationships()}
    assert copy.table("Books").field("author").ref_table == "Authors"
    source.close()
    copy.close()


def test_awkward_values_round_trip(adapter, tmp_path):
    A = AccessColumn
    db = AccessDatabase((AccessTable(
        "Odd", (A("id", "autonumber", key=True), A("t", "text", unique=True), A("m", "longtext"),
                A("n", "number"), A("b", "boolean"), A("d", "date"), A("s", "datetime")),
        ((1, "Łódź \"q\" 日本語", "line1\nline2\ttab", 0.1, True, "2020-02-29", "2026-10-20 23:59:59"),
         (7, "plain", None, -3.0, False, None, None))),))
    path = str(tmp_path / "odd.accdb")
    adapter.write(path, db)
    back = adapter.read(path).tables[0]
    assert [(c.name, c.kind, c.key, c.unique) for c in back.columns] == [
        ("id", "autonumber", True, False), ("t", "text", False, True), ("m", "longtext", False, False),
        ("n", "number", False, False), ("b", "boolean", False, False), ("d", "date", False, False),
        ("s", "datetime", False, False)]
    assert back.rows == db.tables[0].rows[:1] + ((7, "plain", None, -3.0, False, None, None),)


def test_writing_never_overwrites_or_leaves_half_a_file(adapter, tmp_path):
    existing = tmp_path / "x.accdb"
    existing.write_bytes(b"keep me")
    with pytest.raises(FileAccessError):
        adapter.write(str(existing), AccessDatabase(()))
    assert existing.read_bytes() == b"keep me"
    bad = AccessDatabase((AccessTable("T", (AccessColumn("a", "integer"),), ((1,),)),),
                         (AccessLink("T", "a", "Nope", "id"),))
    target = tmp_path / "bad.accdb"
    with pytest.raises(FileFormatError):
        adapter.write(str(target), bad)
    assert not target.exists()


def test_files_that_arent_access_are_refused(adapter, tmp_path):
    junk = tmp_path / "junk.accdb"
    junk.write_bytes(b"not an access file" * 100)
    with pytest.raises(FileFormatError):
        adapter.read(str(junk))
    with pytest.raises(FileAccessError):
        adapter.read(str(tmp_path / "missing.accdb"))


def test_without_java_the_message_says_what_to_do(tmp_path, monkeypatch):
    from folio.infrastructure import access_files
    monkeypatch.setattr(access_files, "find_java", lambda: None)
    jar = tmp_path / "x.jar"
    jar.write_bytes(b"")
    target = tmp_path / "a.accdb"
    target.write_bytes(b"x")
    with pytest.raises(FileFormatError, match="Java"):
        AccessFilesAdapter(jar=jar).read(str(target))

"""Open an Access file (.accdb / .mdb) and edit it in place, with no conversion.

How: the helper (`FolioAccess.jar serve`) keeps the file open through Jackcess. Folio loads
its tables into an in-memory SQLite mirror, which is what queries, forms, reports, search and
undo run on, and every change is applied to the mirror and then to the Access file. If Access
refuses a change the mirror is rolled back (or reloaded), so the two never drift apart.

Jackcess can add rows, fields, tables and relationships but cannot rename, retype or delete
existing fields or tables, so those design changes are refused with an explanation. The
file's own queries, forms and macros are left untouched; Folio's saved queries, forms and
reports live in a hidden `USys_FolioObjects` table inside the file.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from ..application.errors import ConstraintError, DesignError, FileAccessError, FileFormatError
from ..domain.schema import (Field, FieldType, ForeignKey, Table, create_table_sql, quote)
from .access_files import AccessFilesAdapter
from .sqlite import OBJECTS, SqliteDatabase, _translate  # noqa: F401  (OBJECTS: the mirror's table)

ACCESS_TYPES = (".accdb", ".mdb")
HIDDEN_PREFIXES = ("MSys", "USys", "~")
OBJECT_TABLE = "USys_FolioObjects"
_KIND_TO_TYPE = {"autonumber": FieldType.INTEGER, "integer": FieldType.INTEGER,
                 "number": FieldType.NUMBER, "currency": FieldType.CURRENCY,
                 "boolean": FieldType.YES_NO, "date": FieldType.DATE,
                 "datetime": FieldType.DATETIME, "text": FieldType.TEXT,
                 "longtext": FieldType.LONG_TEXT}
_TYPE_TO_KIND = {FieldType.INTEGER: "integer", FieldType.NUMBER: "number",
                 FieldType.CURRENCY: "currency", FieldType.YES_NO: "boolean",
                 FieldType.DATE: "date", FieldType.DATETIME: "datetime",
                 FieldType.TEXT: "text", FieldType.LONG_TEXT: "longtext"}


def is_access_file(path: str) -> bool:
    return Path(path).suffix.lower() in ACCESS_TYPES


def lock_file(path: str) -> Path:
    p = Path(path)
    return p.with_suffix(".laccdb" if p.suffix.lower() == ".accdb" else ".ldb")


class AccessSession:
    """The running helper: one JSON request per line in, one JSON answer per line out."""

    def __init__(self, command: list[str]):
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            self._process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                             stderr=subprocess.DEVNULL, creationflags=flags)
        except OSError as e:
            raise FileFormatError("Folio couldn't start Java to work with Access files.") from e

    def request(self, **message) -> dict:
        process = self._process
        if process.poll() is not None:
            raise FileAccessError("The connection to the Access file was lost.")
        try:
            process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
            process.stdin.flush()
            line = process.stdout.readline()
        except OSError as e:
            raise FileAccessError("The connection to the Access file was lost.") from e
        if not line:
            raise FileAccessError("The connection to the Access file was lost.")
        answer = json.loads(line.decode("utf-8"))
        if not answer.get("ok"):
            raise DesignError("Access refused that change.")
        return answer

    def close(self) -> None:
        process = self._process
        if process.poll() is None:
            try:
                self.request(op="close")
            except Exception:
                pass
            try:
                process.stdin.close()
                process.wait(timeout=10)
            except Exception:
                process.kill()


class AccessBackedDatabase(SqliteDatabase):
    def __init__(self, adapter: AccessFilesAdapter | None = None):
        super().__init__()
        self._adapter = adapter or AccessFilesAdapter()
        self._session: AccessSession | None = None
        self._access_path: str | None = None
        self._backed_up = False
        self._has_objects = False

    @property
    def path(self) -> str | None:
        return self._access_path

    # ---- opening -------------------------------------------------------------------
    def create(self, path: str) -> None:
        target = Path(path)
        if target.exists() and target.stat().st_size:
            raise FileAccessError("That file already exists.")
        from ..application.ports import AccessDatabase
        self._adapter.write(path, AccessDatabase(()))
        self.open(path)

    def open(self, path: str) -> None:
        if not Path(path).is_file():
            raise FileAccessError("The file couldn't be opened.")
        if lock_file(path).exists():
            raise FileAccessError("The file seems to be open in Microsoft Access (or Access closed "
                                  "badly). Close it there, or delete the lock file next to it, "
                                  "and try again.")
        self.close()
        session = AccessSession(self._adapter.command("serve", path))
        try:
            data = session.request(op="load")["data"]
        except DesignError as e:
            session.close()
            raise FileFormatError("Folio couldn't open that Access file (it may be encrypted or "
                                  "from a newer version of Access).") from e
        except Exception:
            session.close()
            raise
        try:
            self._connect(":memory:")  # first: it closes whatever was open before
            self._session, self._access_path, self._backed_up = session, path, False
            self._build(data)
        except Exception:
            session.close()
            raise

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
        self._session = None
        self._access_path = None
        super().close()

    # ---- the mirror ----------------------------------------------------------------
    def _build(self, data: dict) -> None:
        db = self.db
        db.execute("PRAGMA foreign_keys=OFF")  # Access files may hold links nobody enforced
        self._has_objects = False
        tables = {}
        for t in data["tables"]:
            if t["name"].startswith(HIDDEN_PREFIXES) and t["name"] != OBJECT_TABLE:
                continue
            if t["name"] == OBJECT_TABLE:
                self._has_objects = True
                for kind, name, blob in t["rows"]:
                    db.execute(f"INSERT OR REPLACE INTO {OBJECTS} (kind, name, data) VALUES (?,?,?)",
                               [kind, name, blob])
                continue
            tables[t["name"]] = t
        links = {}
        for r in data["relationships"]:
            if r["child"] in tables and r["parent"] in tables:
                links.setdefault(r["child"], []).append(r)
        for name, t in tables.items():
            keys = [c for c in t["columns"] if c["key"]]
            fields = []
            for c in t["columns"]:
                ftype = _KIND_TO_TYPE[c["type"]]
                single = len(keys) == 1 and c["key"]
                fields.append(Field(c["name"], ftype, primary_key=c["key"],
                                    autonumber=single and c["type"] == "autonumber",
                                    required=c["required"] and not c["key"],
                                    unique=c["unique"] and not c["key"],
                                    currency=c.get("currency", "")))
            fks = []
            for r in links.get(name, ()):
                parent = tables[r["parent"]]
                target = next((c for c in parent["columns"] if c["name"] == r["parentField"]), None)
                if target and (target["key"] and sum(1 for c in parent["columns"] if c["key"]) == 1
                               or target["unique"]):
                    fks.append(ForeignKey(r["childField"], r["parent"], r["parentField"]))
            db.execute(create_table_sql(Table(name, tuple(fields), tuple(fks))))
        for name, t in tables.items():
            self._fill(name, [c["name"] for c in t["columns"]], t["rows"])
        db.execute("PRAGMA foreign_keys=ON")

    def _fill(self, name: str, columns: list[str], rows: list) -> None:
        if rows:
            self.db.executemany(
                f"INSERT INTO {quote(name)} ({', '.join(quote(c) for c in columns)}) "
                f"VALUES ({', '.join('?' * len(columns))})",
                [[int(v) if isinstance(v, bool) else v for v in row] for row in rows])

    def _resync(self) -> None:
        """Reload everything from the Access file (after a change that went wrong half way)."""
        data = self._session.request(op="load")["data"]
        self.db.execute("PRAGMA foreign_keys=OFF")
        for (name,) in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
            self.db.execute(f"DROP TABLE {quote(name)}")
        self.db.execute(f"CREATE TABLE {OBJECTS} (kind TEXT NOT NULL, name TEXT NOT NULL, "
                        "data TEXT NOT NULL, PRIMARY KEY (kind, name))")
        self._build(data)

    def _reload_table(self, name: str) -> None:
        t = self._session.request(op="dump", table=name)["table"]
        self.db.execute("PRAGMA foreign_keys=OFF")
        self.db.execute(f"DELETE FROM {quote(name)}")
        self._fill(name, [c["name"] for c in t["columns"]], t["rows"])
        self.db.execute("PRAGMA foreign_keys=ON")

    # ---- writing safely ------------------------------------------------------------
    def _before_write(self) -> None:
        """Keep one copy of the file as it was before Folio first changed it."""
        if self._backed_up or not self._access_path:
            return
        source = Path(self._access_path)
        backup = source.with_name(f"{source.stem}.folio-backup{source.suffix}")
        if not backup.exists():
            try:
                shutil.copy2(source, backup)
            except OSError as e:
                raise FileAccessError("Folio couldn't make a safety copy of the Access file "
                                      "before changing it.") from e
        self._backed_up = True

    def _send(self, **message) -> dict:
        self._before_write()
        return self._session.request(**message)

    @staticmethod
    def _alias_pk(table: Table) -> Field | None:
        pk = table.primary_key
        return pk[0] if len(pk) == 1 and pk[0].type is FieldType.INTEGER else None

    # ---- rows ----------------------------------------------------------------------
    def insert_row(self, table: Table, values: dict, row_id: int | None = None) -> int:
        supplied = set(values)
        with self._tx():
            rid = super().insert_row(table, values, row_id)
            stored = self.get_row(table, rid) or {}
            autos = [f for f in table.fields if f.autonumber]
            send = {k: v for k, v in stored.items() if v is not None
                    and not (k in {a.name for a in autos} and k not in supplied)}
            answer = self._send(op="insert", table=table.name, values=send)
            alias = self._alias_pk(table)
            for f in autos:
                if f.name in supplied:
                    continue
                generated = answer["generated"].get(f.name)
                if generated is not None and generated != stored.get(f.name):
                    self.db.execute(f"UPDATE {quote(table.name)} SET {quote(f.name)} = ? WHERE rowid = ?",
                                    [generated, rid])
                    if alias is not None and alias.name == f.name:
                        rid = generated
        return rid

    def update_row(self, table: Table, row_id: int, values: dict) -> None:
        if not values:
            return
        old = self.get_row(table, row_id)
        if old is None:
            return
        with self._tx():
            super().update_row(table, row_id, values)
            self._send(op="update", table=table.name, match=old, values=values)

    def delete_rows(self, table: Table, row_ids: list[int]) -> None:
        olds = [o for o in (self.get_row(table, r) for r in row_ids) if o is not None]
        done = 0
        try:
            with self._tx():
                super().delete_rows(table, row_ids)
                for old in olds:
                    self._send(op="delete", table=table.name, match=old)
                    done += 1
        except Exception:
            if done:
                self._resync()  # some rows are already gone from the file
            raise

    def bulk_insert(self, table: Table, columns: list[str], rows: list[list]) -> int:
        with self._tx():
            super().bulk_insert(table, columns, rows)
            self._send(op="bulkInsert", table=table.name, columns=columns, rows=rows)
        self._reload_table(table.name)  # pick up the numbers Access gave the new rows
        return len(rows)

    # ---- structure -----------------------------------------------------------------
    @staticmethod
    def _spec(table: Table) -> dict:
        keys = [f.name for f in table.fields if f.primary_key]
        return {"name": table.name, "columns": [
            {"name": f.name, "type": "autonumber" if f.autonumber else _TYPE_TO_KIND[f.type],
             "key": f.primary_key, "unique": f.unique, "required": f.required,
             "currency": f.currency} for f in table.fields], "rows": []}

    def create_table(self, table: Table) -> None:
        super().create_table(table)
        try:
            self._send(op="createTable", spec=self._spec(table))
            for key in table.foreign_keys:
                self._send(op="addRelationship", relationship={
                    "parent": key.ref_table, "parentField": key.ref_field, "child": table.name,
                    "childField": key.field, "cascade": key.on_delete == "CASCADE",
                    "setNull": key.on_delete == "SET NULL"})
        except Exception:
            self.db.execute(f"DROP TABLE IF EXISTS {quote(table.name)}")
            raise

    def rebuild_table(self, old_name: str, table: Table, column_map: dict[str, str | None]) -> None:
        old = next((t for t in self.read_schema() if t.name == old_name), None)
        refuse = DesignError("Folio can't change or remove existing fields of an Access file. "
                             "You can add fields and links; for anything else use Access.")
        if old is None or old_name != table.name:
            raise refuse
        mapped = {o for o in column_map.values() if o}
        if mapped != {f.name for f in old.fields}:
            raise refuse  # a field was removed
        added = []
        for f in table.fields:
            source = column_map.get(f.name)
            if source is None:
                if f.primary_key or f.autonumber:
                    raise refuse
                added.append(f)
                continue
            before = old.field(source)
            if (source != f.name or before.type is not f.type or before.primary_key != f.primary_key
                    or before.autonumber != f.autonumber or before.required != f.required
                    or before.unique != f.unique or (before.default or "") != (f.default or "")
                    or before.currency != f.currency):
                raise refuse
        old_keys = {(k.field, k.ref_table, k.ref_field, k.on_delete) for k in old.foreign_keys}
        new_keys = {(k.field, k.ref_table, k.ref_field, k.on_delete) for k in table.foreign_keys}
        if old_keys - new_keys:
            raise refuse  # Jackcess can't delete a relationship
        super().rebuild_table(old_name, table, column_map)
        try:
            for f in added:
                self._send(op="addColumn", table=table.name, column={
                    "name": f.name, "type": _TYPE_TO_KIND[f.type], "required": f.required,
                    "key": False, "currency": f.currency})
            if added:
                self._reload_table(table.name)  # e.g. Access gives Yes/No fields "No", never empty
            for field, parent, parent_field, action in sorted(new_keys - old_keys):
                self._send(op="addRelationship", relationship={
                    "parent": parent, "parentField": parent_field, "child": table.name,
                    "childField": field, "cascade": action == "CASCADE",
                    "setNull": action == "SET NULL"})
        except Exception:
            self._resync()
            raise

    def drop_table(self, name: str) -> None:
        raise DesignError("Folio can't delete tables from an Access file.")

    def compact(self) -> None:
        raise DesignError("Access files can't be compacted from Folio.")

    # ---- Folio's own saved queries, forms and reports --------------------------------
    def _ensure_objects(self) -> None:
        if self._has_objects:
            return
        self._send(op="createTable", spec={"name": OBJECT_TABLE, "columns": [
            {"name": "kind", "type": "text", "key": True},
            {"name": "name", "type": "text", "key": True},
            {"name": "data", "type": "longtext"}], "rows": []})
        self._has_objects = True

    def save_object(self, kind: str, name: str, data: dict) -> None:
        exists = self.load_object(kind, name) is not None
        text = json.dumps(data)
        self._ensure_objects()
        if exists:
            self._send(op="update", table=OBJECT_TABLE, match={"kind": kind, "name": name},
                       values={"data": text})
        else:
            self._send(op="insert", table=OBJECT_TABLE, values={"kind": kind, "name": name, "data": text})
        super().save_object(kind, name, data)

    def delete_object(self, kind: str, name: str) -> None:
        if self.load_object(kind, name) is not None:
            self._send(op="delete", table=OBJECT_TABLE, match={"kind": kind, "name": name})
        super().delete_object(kind, name)

    def rename_object(self, kind: str, old: str, new: str) -> None:
        if self.load_object(kind, old) is not None:
            self._send(op="update", table=OBJECT_TABLE, match={"kind": kind, "name": old},
                       values={"name": new})
        super().rename_object(kind, old, new)


class DatabaseRouter:
    """The one database gateway the app sees: SQLite files go to SqliteDatabase, Access files
    to AccessBackedDatabase, chosen by the file's extension."""

    def __init__(self, sqlite: SqliteDatabase | None = None,
                 access: AccessBackedDatabase | None = None):
        self._sqlite = sqlite or SqliteDatabase()
        self._access = access or AccessBackedDatabase()
        self._current = self._sqlite

    @property
    def path(self) -> str | None:
        return self._current.path

    def _pick(self, path: str):
        return self._access if is_access_file(path) else self._sqlite

    def create(self, path: str) -> None:
        self.close()
        target = self._pick(path)
        target.create(path)
        self._current = target

    def open(self, path: str) -> None:
        self.close()
        target = self._pick(path)
        target.open(path)
        self._current = target

    def close(self) -> None:
        self._current.close()

    def __getattr__(self, name):
        return getattr(self._current, name)

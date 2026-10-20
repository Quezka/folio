"""A Folio database is a plain SQLite file; this is the adapter that reads and writes it."""
from __future__ import annotations

import itertools
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from ..application.errors import (ConstraintError, DesignError, FileAccessError, FileFormatError,
                                  NotOpenError)
from ..application.ports import RowQuery
from ..domain.schema import (Field, FieldType, ForeignKey, Table, create_table_sql, parse_declared,
                             quote)

HEADER = b"SQLite format 3\x00"
OBJECTS = "_folio_objects"
_HIDDEN = ("sqlite_%", "\\_folio%")


def _translate(error: sqlite3.Error) -> Exception:
    text = str(error)
    if isinstance(error, sqlite3.IntegrityError):
        if "NOT NULL" in text:
            return ConstraintError("A required field can't be left empty.")
        if "UNIQUE" in text or "PRIMARY KEY" in text:
            return ConstraintError("That value is already used. It has to be unique.")
        if "FOREIGN KEY" in text:
            return ConstraintError("That points at a record that doesn't exist, or other "
                                   "records still depend on this one.")
        return ConstraintError("That change breaks a rule of the table.")
    if "readonly" in text.lower() or "locked" in text.lower():
        return FileAccessError("The database file can't be written to (is it read-only or open "
                               "elsewhere?).")
    return DesignError(text)


def _default_text(dflt: str | None) -> str | None:
    if dflt is None:
        return None
    d = dflt.strip()
    low = d.lower()
    if "date('now'" in low and "datetime" not in low:
        return "today"
    if "datetime('now'" in low or low == "current_timestamp":
        return "now"
    if low == "current_date":
        return "today"
    if len(d) >= 2 and d[0] == "'" and d[-1] == "'":
        return d[1:-1].replace("''", "'")
    return d


class SqliteDatabase:
    _savepoints = itertools.count(1)

    def __init__(self):
        self._db: sqlite3.Connection | None = None
        self._path: str | None = None

    @contextmanager
    def _tx(self):
        """All or nothing; nests, so a subclass can wrap further work around a call."""
        name = f"folio_{next(self._savepoints)}"
        self.db.execute(f"SAVEPOINT {name}")
        try:
            yield
        except BaseException:
            self.db.execute(f"ROLLBACK TO {name}")
            self.db.execute(f"RELEASE {name}")
            raise
        self.db.execute(f"RELEASE {name}")

    # ---- lifecycle -----------------------------------------------------------------
    @property
    def path(self) -> str | None:
        return self._path

    @property
    def db(self) -> sqlite3.Connection:
        if self._db is None:
            raise NotOpenError("No database is open.")
        return self._db

    def _connect(self, path: str):
        try:
            db = sqlite3.connect(path, isolation_level=None)
            db.execute("PRAGMA foreign_keys=ON")
            db.execute(f"CREATE TABLE IF NOT EXISTS {OBJECTS} (kind TEXT NOT NULL, "
                       "name TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (kind, name))")
        except sqlite3.DatabaseError as e:
            raise FileFormatError("That file isn't a database Folio can open.") from e
        except sqlite3.Error as e:
            raise FileAccessError("The file couldn't be opened.") from e
        self.close()
        self._db, self._path = db, path

    def create(self, path: str) -> None:
        target = Path(path)
        if target.exists() and target.stat().st_size:
            raise FileAccessError("That file already exists.")
        self._connect(path)

    def open(self, path: str) -> None:
        target = Path(path)
        try:
            with target.open("rb") as f:
                head = f.read(16)
        except OSError as e:
            raise FileAccessError("The file couldn't be opened.") from e
        if head and head != HEADER:
            raise FileFormatError("That file isn't a database Folio can open.")
        self._connect(path)

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
        self._db, self._path = None, None

    # ---- structure -----------------------------------------------------------------
    def read_schema(self) -> list[Table]:
        db = self.db
        rows = db.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE ? "
            "AND name NOT LIKE ? ESCAPE '\\' ORDER BY name COLLATE NOCASE", _HIDDEN).fetchall()
        return [self._read_table(name, sql or "") for name, sql in rows]

    def _read_table(self, name: str, sql: str) -> Table:
        db = self.db
        info = db.execute(f"PRAGMA table_info({quote(name)})").fetchall()
        pk_columns = [r for r in info if r[5]]
        unique = set()
        for _seq, index, is_unique, origin, _partial in db.execute(
                f"PRAGMA index_list({quote(name)})").fetchall():
            if is_unique and origin == "u":
                cols = db.execute(f"PRAGMA index_info({quote(index)})").fetchall()
                if len(cols) == 1:
                    unique.add(cols[0][2])
        upper = sql.upper()
        auto = "AUTOINCREMENT" in upper
        fields = []
        for _cid, col, declared, notnull, dflt, pk in info:
            ftype, currency = parse_declared(declared)
            is_auto = pk and len(pk_columns) == 1 and ftype is FieldType.INTEGER and (
                auto or (declared or "").upper() == "INTEGER")
            fields.append(Field(col, ftype, primary_key=bool(pk), autonumber=bool(is_auto),
                                required=bool(notnull) and not pk, unique=col in unique,
                                default=_default_text(dflt), currency=currency))
        keys, composite = [], False
        grouped: dict[int, list] = {}
        for row in db.execute(f"PRAGMA foreign_key_list({quote(name)})").fetchall():
            grouped.setdefault(row[0], []).append(row)
        for parts in grouped.values():
            if len(parts) > 1:
                composite = True
                continue
            _id, _seq, ref, local, remote, _upd, on_del, _m = parts[0]
            if remote is None:  # points at the parent's primary key
                parent = db.execute(f"PRAGMA table_info({quote(ref)})").fetchall()
                remote = next((r[1] for r in parent if r[5]), "rowid")
            keys.append(ForeignKey(local, ref, remote, on_del if on_del in
                                   ("CASCADE", "SET NULL") else "NO ACTION"))
        locked = composite or any(w in upper for w in ("CHECK", "GENERATED", "WITHOUT ROWID",
                                                        "COLLATE", "AS (")) \
            or any(pk and len(pk_columns) > 1 and "AUTOINCREMENT" in upper for *_x, pk in info)
        return Table(name, tuple(fields), tuple(keys), locked)

    def create_table(self, table: Table) -> None:
        try:
            self.db.execute(create_table_sql(table))
        except sqlite3.Error as e:
            raise _translate(e) from e

    def rebuild_table(self, old_name: str, table: Table, column_map: dict[str, str | None]) -> None:
        db = self.db
        tmp = f"_folio_new_{table.name}"
        db.execute("PRAGMA foreign_keys=OFF")
        try:
            db.execute("BEGIN")
            if old_name != table.name:
                db.execute(f"ALTER TABLE {quote(old_name)} RENAME TO {quote(table.name)}")
            db.execute(create_table_sql(table, tmp))
            pairs = [(n, o) for n, o in column_map.items() if o is not None]
            if pairs:
                db.execute(f"INSERT INTO {quote(tmp)} ({', '.join(quote(n) for n, _ in pairs)}) "
                           f"SELECT {', '.join(quote(o) for _, o in pairs)} FROM {quote(table.name)}")
            db.execute(f"DROP TABLE {quote(table.name)}")
            db.execute(f"ALTER TABLE {quote(tmp)} RENAME TO {quote(table.name)}")
            if db.execute("PRAGMA foreign_key_check").fetchall():
                raise sqlite3.IntegrityError("FOREIGN KEY constraint failed")
            db.execute("COMMIT")
        except sqlite3.Error as e:
            if db.in_transaction:
                db.execute("ROLLBACK")
            if isinstance(e, sqlite3.IntegrityError):
                raise ConstraintError("Some rows don't fit the new design (an empty required "
                                      "field, a repeated unique value or a broken link).") from e
            raise _translate(e) from e
        except Exception:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.execute("PRAGMA foreign_keys=ON")

    def drop_table(self, name: str) -> None:
        try:
            self.db.execute(f"DROP TABLE {quote(name)}")
        except sqlite3.Error as e:
            raise _translate(e) from e

    # ---- rows ----------------------------------------------------------------------
    @staticmethod
    def _where(columns: list[str], q: RowQuery) -> tuple[str, list]:
        conds, params = [], []
        if q.search.strip():
            like = "%" + q.search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            conds.append("(" + " OR ".join(f"CAST({quote(c)} AS TEXT) LIKE ? ESCAPE '\\'"
                                           for c in columns) + ")")
            params += [like] * len(columns)
        for column, op, value in q.filters:
            if column not in columns:
                continue
            if op == "null":
                conds.append(f"({quote(column)} IS NULL OR {quote(column)} = '')")
            elif op == "notnull":
                conds.append(f"({quote(column)} IS NOT NULL AND {quote(column)} <> '')")
            elif op in ("=", "<>"):
                conds.append(f"{quote(column)} {op} ?")
                params.append(value)
        return (" WHERE " + " AND ".join(conds)) if conds else "", params

    def _order(self, columns: list[str], q: RowQuery, default: str) -> str:
        if q.order_by in columns:
            return f" ORDER BY {quote(q.order_by)} {'DESC' if q.descending else 'ASC'}, {default}"
        return f" ORDER BY {default}"

    def count_table(self, table: Table, q: RowQuery) -> int:
        names = [f.name for f in table.fields]
        where, params = self._where(names, q)
        return self.db.execute(f"SELECT COUNT(*) FROM {quote(table.name)}{where}", params).fetchone()[0]

    def fetch_table(self, table: Table, q: RowQuery, offset: int, limit: int) -> list[tuple]:
        names = [f.name for f in table.fields]
        where, params = self._where(names, q)
        cols = ", ".join(quote(n) for n in names)
        sql = (f"SELECT rowid, {cols} FROM {quote(table.name)}{where}"
               f"{self._order(names, q, 'rowid')} LIMIT ? OFFSET ?")
        return self.db.execute(sql, params + [limit, offset]).fetchall()

    def get_row(self, table: Table, row_id: int) -> dict | None:
        names = [f.name for f in table.fields]
        row = self.db.execute(f"SELECT {', '.join(quote(n) for n in names)} FROM "
                              f"{quote(table.name)} WHERE rowid = ?", [row_id]).fetchone()
        return dict(zip(names, row)) if row else None

    def insert_row(self, table: Table, values: dict, row_id: int | None = None) -> int:
        data = dict(values)
        if row_id is not None:
            data["rowid"] = row_id
        try:
            if data:
                self.db.execute(f"INSERT INTO {quote(table.name)} ({', '.join(quote(k) for k in data)}) "
                                f"VALUES ({', '.join('?' * len(data))})", list(data.values()))
            else:
                self.db.execute(f"INSERT INTO {quote(table.name)} DEFAULT VALUES")
            return self.db.execute("SELECT last_insert_rowid()").fetchone()[0]
        except sqlite3.Error as e:
            raise _translate(e) from e

    def update_row(self, table: Table, row_id: int, values: dict) -> None:
        if not values:
            return
        try:
            self.db.execute(f"UPDATE {quote(table.name)} SET "
                            f"{', '.join(quote(k) + ' = ?' for k in values)} WHERE rowid = ?",
                            [*values.values(), row_id])
        except sqlite3.Error as e:
            raise _translate(e) from e

    def delete_rows(self, table: Table, row_ids: list[int]) -> None:
        try:
            with self._tx():
                self.db.executemany(f"DELETE FROM {quote(table.name)} WHERE rowid = ?",
                                    [(r,) for r in row_ids])
        except sqlite3.Error as e:
            raise _translate(e) from e

    def bulk_insert(self, table: Table, columns: list[str], rows: list[list]) -> int:
        sql = (f"INSERT INTO {quote(table.name)} ({', '.join(quote(c) for c in columns)}) "
               f"VALUES ({', '.join('?' * len(columns))})")
        try:
            with self._tx():
                self.db.executemany(sql, rows)
        except sqlite3.Error as e:
            raise _translate(e) from e
        return len(rows)

    def lookup(self, table: Table, key_field: str, label_field: str) -> list[tuple]:
        return self.db.execute(
            f"SELECT {quote(key_field)}, {quote(label_field)} FROM {quote(table.name)} "
            f"ORDER BY {quote(label_field)} COLLATE NOCASE").fetchall()

    # ---- queries -------------------------------------------------------------------
    def check_select(self, sql: str) -> list[str]:
        if not re.match(r"\s*(select|with)\b", sql, re.I):
            raise DesignError("A query can only read data: it has to start with SELECT.")
        try:
            cur = self.db.execute(f"SELECT * FROM ({sql.strip().rstrip(';')}) AS q LIMIT 0")
        except sqlite3.Error as e:
            raise DesignError(str(e)) from e
        return [d[0] for d in cur.description]

    def _wrapped(self, sql: str, q: RowQuery):
        names = self.check_select(sql)
        where, params = self._where(names, q)
        base = f"SELECT * FROM ({sql.strip().rstrip(';')}) AS q{where}"
        return names, base, params

    def count_query(self, sql: str, q: RowQuery) -> int:
        _names, base, params = self._wrapped(sql, q)
        return self.db.execute(f"SELECT COUNT(*) FROM ({base})", params).fetchone()[0]

    def fetch_query(self, sql: str, q: RowQuery, offset: int, limit: int):
        names, base, params = self._wrapped(sql, q)
        order = self._order(names, q, "1") if q.order_by in names else ""
        rows = self.db.execute(f"{base}{order} LIMIT ? OFFSET ?", params + [limit, offset]).fetchall()
        return names, rows

    # ---- saved objects -------------------------------------------------------------
    def list_objects(self, kind: str) -> list[str]:
        return [r[0] for r in self.db.execute(
            f"SELECT name FROM {OBJECTS} WHERE kind = ? ORDER BY name COLLATE NOCASE", [kind])]

    def load_object(self, kind: str, name: str) -> dict | None:
        row = self.db.execute(f"SELECT data FROM {OBJECTS} WHERE kind = ? AND name = ?",
                              [kind, name]).fetchone()
        return json.loads(row[0]) if row else None

    def save_object(self, kind: str, name: str, data: dict) -> None:
        try:
            self.db.execute(f"INSERT OR REPLACE INTO {OBJECTS} (kind, name, data) VALUES (?,?,?)",
                            [kind, name, json.dumps(data)])
        except sqlite3.Error as e:
            raise _translate(e) from e

    def delete_object(self, kind: str, name: str) -> None:
        self.db.execute(f"DELETE FROM {OBJECTS} WHERE kind = ? AND name = ?", [kind, name])

    def rename_object(self, kind: str, old: str, new: str) -> None:
        try:
            self.db.execute(f"UPDATE {OBJECTS} SET name = ? WHERE kind = ? AND name = ?",
                            [new, kind, old])
        except sqlite3.Error as e:
            raise _translate(e) from e

    def compact(self) -> None:
        try:
            self.db.execute("VACUUM")
        except sqlite3.Error as e:
            raise _translate(e) from e

"""What the use cases need from the outside world, as interfaces. Adapters live in
`infrastructure`; `bootstrap` plugs them in."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..domain.schema import Table


@dataclass(frozen=True)
class RowQuery:
    """Which rows of a table or query to read, and in what order."""
    search: str = ""  # text that must appear in some column
    filters: tuple[tuple[str, str, object], ...] = ()  # (column, "=" | "<>" | "null" | "notnull", value)
    order_by: str = ""
    descending: bool = False


class DatabaseGateway(Protocol):
    """One database file. Every call is saved at once (no separate "save" step)."""

    @property
    def path(self) -> str | None: ...

    def create(self, path: str) -> None: ...
    def open(self, path: str) -> None:
        """Raises FileFormatError / FileAccessError."""
        ...
    def close(self) -> None: ...

    # -- structure
    def read_schema(self) -> list[Table]: ...
    def create_table(self, table: Table) -> None: ...
    def rebuild_table(self, old_name: str, table: Table, column_map: dict[str, str | None]) -> None:
        """Change a table's design, keeping its rows. `column_map` says which old column
        feeds each new one (None: a new column)."""
        ...
    def drop_table(self, name: str) -> None: ...

    # -- rows
    def count_table(self, table: Table, query: RowQuery) -> int: ...
    def fetch_table(self, table: Table, query: RowQuery, offset: int, limit: int) -> list[tuple]:
        """Rows as (row id, value of each field…)."""
        ...
    def get_row(self, table: Table, row_id: int) -> dict | None: ...
    def insert_row(self, table: Table, values: dict, row_id: int | None = None) -> int: ...
    def update_row(self, table: Table, row_id: int, values: dict) -> None: ...
    def delete_rows(self, table: Table, row_ids: list[int]) -> None: ...
    def bulk_insert(self, table: Table, columns: list[str], rows: list[list]) -> int: ...
    def lookup(self, table: Table, key_field: str, label_field: str) -> list[tuple]: ...

    # -- queries
    def check_select(self, sql: str) -> list[str]:
        """The column names of a SELECT, or raises QueryProblem when it can't run."""
        ...
    def count_query(self, sql: str, query: RowQuery) -> int: ...
    def fetch_query(self, sql: str, query: RowQuery, offset: int, limit: int) -> tuple[list[str], list[tuple]]: ...

    # -- saved queries, forms, reports and layouts live in the same file
    def list_objects(self, kind: str) -> list[str]: ...
    def load_object(self, kind: str, name: str) -> dict | None: ...
    def save_object(self, kind: str, name: str, data: dict) -> None: ...
    def delete_object(self, kind: str, name: str) -> None: ...
    def rename_object(self, kind: str, old: str, new: str) -> None: ...

    def compact(self) -> None: ...


class CsvFiles(Protocol):
    def read(self, path: str) -> list[list[str]]:
        """All rows of a CSV/TSV file (delimiter and encoding are detected)."""
        ...
    def write(self, path: str, header: list[str], rows: list[list]) -> None: ...


@dataclass(frozen=True)
class AccessColumn:
    name: str
    kind: str  # autonumber, integer, number, currency, boolean, date, datetime, text, longtext
    key: bool = False
    unique: bool = False
    required: bool = False
    currency: str = ""  # for "currency" columns: the code, e.g. "EUR"


@dataclass(frozen=True)
class AccessTable:
    name: str
    columns: tuple[AccessColumn, ...]
    rows: tuple[tuple, ...]  # dates and times as ISO text, yes/no as booleans
    skipped: tuple[str, ...] = ()  # columns left out (pictures, attachments, OLE objects…)


@dataclass(frozen=True)
class AccessLink:
    """One table's field pointing at another table's key."""
    child: str
    child_field: str
    parent: str
    parent_field: str
    cascade: bool = False
    set_null: bool = False


@dataclass(frozen=True)
class AccessDatabase:
    tables: tuple[AccessTable, ...]
    links: tuple[AccessLink, ...] = ()


class AccessFiles(Protocol):
    def read(self, path: str) -> AccessDatabase:
        """The tables, rows and relationships of a Microsoft Access file (.accdb / .mdb).
        Raises FileFormatError / FileAccessError."""
        ...

    def write(self, path: str, database: AccessDatabase) -> None:
        """Create a new Access file (.accdb, or .mdb for the old format). Refuses to
        overwrite. Raises FileFormatError / FileAccessError."""
        ...


class KeyValueStore(Protocol):
    """Small persistent settings (e.g. when updates were last checked)."""

    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str | None) -> None: ...


# ---- updates ------------------------------------------------------------------------

@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    url: str
    size: int
    sha256: str | None = None  # published checksum, when the host provides one


@dataclass(frozen=True)
class ReleaseInfo:
    version: str  # e.g. "0.2.0"
    notes: str  # Markdown
    page_url: str
    assets: tuple[ReleaseAsset, ...]


class ReleaseFeed(Protocol):
    """Where new versions are published (e.g. GitHub releases). Network only."""

    def latest(self) -> ReleaseInfo | None: ...

    def download(self, asset: ReleaseAsset, progress) -> str:
        """Fetch the file, check its size and checksum, and return its local path.
        `progress(done_bytes, total_bytes)` is called as it goes."""
        ...


class UpdateInstaller(Protocol):
    """Installs a downloaded release on this platform."""

    def supported(self) -> bool:
        """False when this copy can't update itself (e.g. running from source)."""
        ...

    def pick(self, assets: tuple[ReleaseAsset, ...]) -> ReleaseAsset | None: ...

    def install(self, path: str) -> bool:
        """Install it. True: the installer took over and the app must quit now (it will be
        started again). False: installed, restart the app to use the new version."""
        ...

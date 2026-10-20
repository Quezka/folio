"""Reads and creates Microsoft Access files (.accdb / .mdb) through `FolioAccess.jar`.

The jar (java/src/FolioAccess.java, built on Jackcess) does the format work and needs a Java
runtime: the one shipped inside Folio's Windows install (`jre/`), or the system's `java`."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ..application.errors import FileAccessError, FileFormatError
from ..application.ports import AccessColumn, AccessDatabase, AccessLink, AccessTable

JAR = "FolioAccess.jar"
TIMEOUT = 600  # seconds; a big database takes a while


def _app_dirs() -> list[Path]:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return [Path(sys.executable).parent, base]
    return [Path(__file__).resolve().parent.parent.parent / "build",
            Path(__file__).resolve().parent.parent / "assets"]


def find_jar() -> Path | None:
    for folder in _app_dirs():
        for candidate in (folder / "java" / JAR, folder / JAR):
            if candidate.is_file():
                return candidate
    return None


def find_java() -> str | None:
    exe = "java.exe" if sys.platform == "win32" else "java"
    for folder in _app_dirs():
        bundled = folder / "jre" / "bin" / exe
        if bundled.is_file():
            return str(bundled)
    home = os.environ.get("JAVA_HOME")
    if home and (Path(home) / "bin" / exe).is_file():
        return str(Path(home) / "bin" / exe)
    return shutil.which("java")


class AccessFilesAdapter:
    def __init__(self, java: str | None = None, jar: Path | None = None):
        self._java = java
        self._jar = jar

    def _command(self, *args: str) -> list[str]:
        java = self._java or find_java()
        jar = self._jar or find_jar()
        if jar is None:
            raise FileFormatError("Folio's Access helper is missing from this installation.")
        if java is None:
            raise FileFormatError("Access files need Java. Install a Java runtime "
                                  "(for example the default-jre-headless package) and try again.")
        return [java, "-Xmx1g", "-Dfile.encoding=UTF-8", "-jar", str(jar), *args]

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            return subprocess.run(self._command(*args), capture_output=True, timeout=TIMEOUT,
                                  creationflags=flags)
        except subprocess.TimeoutExpired as e:
            raise FileAccessError("Reading or writing the Access file took too long.") from e
        except OSError as e:
            raise FileFormatError("Folio couldn't start Java to work with Access files.") from e

    # ---- reading ---------------------------------------------------------------------
    def read(self, path: str) -> AccessDatabase:
        if not Path(path).is_file():
            raise FileAccessError("The file couldn't be opened.")
        done = self._run("read", path)
        if done.returncode != 0:
            raise FileFormatError("Folio couldn't read that Access file (it may be encrypted "
                                  "or from a newer version of Access).")
        try:
            data = json.loads(done.stdout.decode("utf-8"))
            tables = tuple(AccessTable(
                t["name"],
                tuple(AccessColumn(c["name"], c["type"], c["key"], c["unique"], c["required"])
                      for c in t["columns"]),
                tuple(tuple(r) for r in t["rows"]), tuple(t["skipped"]))
                for t in data["tables"])
            links = tuple(AccessLink(r["child"], r["childField"], r["parent"], r["parentField"],
                                     r["cascade"], r["setNull"]) for r in data["relationships"])
        except (ValueError, KeyError, TypeError) as e:
            raise FileFormatError("Folio couldn't read that Access file (it may be encrypted "
                                  "or from a newer version of Access).") from e
        return AccessDatabase(tables, links)

    # ---- writing ---------------------------------------------------------------------
    def write(self, path: str, database: AccessDatabase) -> None:
        if Path(path).exists() and Path(path).stat().st_size:
            raise FileAccessError("That file already exists.")
        spec = {
            "tables": [{
                "name": t.name,
                "columns": [{"name": c.name, "type": c.kind, "key": c.key, "unique": c.unique,
                             "required": c.required} for c in t.columns],
                "rows": [list(r) for r in t.rows]} for t in database.tables],
            "relationships": [{"child": k.child, "childField": k.child_field,
                               "parent": k.parent, "parentField": k.parent_field,
                               "cascade": k.cascade, "setNull": k.set_null}
                              for k in database.links],
        }
        fd, temp = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(spec, f)
            done = self._run("write", path, temp)
        finally:
            Path(temp).unlink(missing_ok=True)
        if done.returncode != 0:
            Path(path).unlink(missing_ok=True)  # never leave half a file
            raise FileFormatError("Folio couldn't create the Access file.")

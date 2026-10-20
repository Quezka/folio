"""Reading and writing CSV / TSV files."""
from __future__ import annotations

import csv
from pathlib import Path

from ..application.errors import FileAccessError, FileFormatError


class CsvFilesAdapter:
    def read(self, path: str) -> list[list[str]]:
        try:
            raw = Path(path).read_bytes()
        except OSError as e:
            raise FileAccessError("The file couldn't be read.") from e
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("latin-1")
        sample = text[:20000]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        try:
            rows = [row for row in csv.reader(text.splitlines(keepends=True), dialect)]
        except csv.Error as e:
            raise FileFormatError("That file isn't a table of values.") from e
        return [r for r in rows if any(c.strip() for c in r)]

    def write(self, path: str, header: list[str], rows: list[list]) -> None:
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(header)
                writer.writerows([["" if v is None else v for v in row] for row in rows])
        except OSError as e:
            raise FileAccessError("The file couldn't be written.") from e

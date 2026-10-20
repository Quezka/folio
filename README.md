# Folio

A friendlier take on the desktop database, in the spirit of [Quire](../quire) and
[Ligature](../ligature): tables, queries, forms and reports in one file you can keep.

- **Tables** in a spreadsheet-like datasheet: typed columns, links shown by name with a
  drop-down, search, sort, filter by value, and undo/redo for every edit. A designer for fields,
  keys, required/unique/default values and links. CSV import (types guessed) and export.
- **Queries** built by ticking fields and typing criteria (`>= 10`, `between 1 and 9`,
  `like "A*"`, `"Rome" or "Milan"`, totals and grouping), with the SQL shown live and editable.
- **Forms**: one record at a time, laid out in 1–3 columns.
- **Reports**: grouped, sorted and totalled; preview, print or export to PDF.
- **Relationships** diagram you can rearrange and edit.
- **Access files**: open an `.accdb` / `.mdb` to convert it into a Folio database (tables, rows,
  keys and relationships), and *Export to Access…* to create an `.accdb` from yours
  (see `docs/access.md`).
- Your data lives in a plain **SQLite** file (`.folio`, or any `.db` / `.sqlite`), so nothing
  is locked in. Every change is saved at once.

English, Italian and Russian. Light and dark. GPL-3.0-or-later.

## Run

    python -m venv .venv && .venv/bin/pip install -e . pytest
    .venv/bin/folio --demo
    QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q

# Folio

Python 3.10+ / PySide6 desktop app (Linux + Windows): a friendlier Microsoft Access (tables,
queries, forms, reports) over a plain SQLite file. Sibling of Quire (`../quire`) and Ligature
(`../ligature`): same look, same toolkit, same release process.

- Layers: `folio/domain` → `folio/application` → `folio/infrastructure` + `folio/presentation`; wired in `folio/bootstrap.py`. `tests/test_architecture.py` enforces it; the UI never imports the domain, and use cases never take or return domain classes (the application has its own copies in `application/inputs.py` / `records.py`, converted in `workspace.py`).
- Run: `.venv/bin/folio --demo`. Test: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (check the exit code). The venv is `--without-pip` and borrows `../ligature/.venv` site-packages through a `.pth` file.
- One gateway (`infrastructure/sqlite.SqliteDatabase`); every call is committed at once. Saved queries, forms, reports and the relationships layout live in the same file, in `_folio_objects` (hidden from the table list).
- Table design changes rebuild the table (SQLite's 12-step procedure) in `rebuild_table`; tables with checks, composite keys etc. are `locked` (rows editable, design not).
- Data edits go through `Workspace` and are undoable (closures in `_Undo`); a schema change clears the stack.
- A "source" is `Source(kind, name)`: `table`, saved `query`, or raw `sql` (query preview).
- Access (`.accdb`/`.mdb`, read and create): `infrastructure/access_files.py` runs `FolioAccess.jar` (`java/src/FolioAccess.java`, built on Jackcess, JSON over stdout / a spec file). `scripts/fetch_jackcess.py` downloads the checksum-pinned jars into `java/lib` (gitignored); `scripts/build_java.py` makes `build/java/FolioAccess.jar` (and, for Windows, a jlink'd `build/jre`). The .deb depends on `default-jre-headless`; the Windows installer ships its own runtime. `tests/test_access_java.py` uses the real jar (skips without Java/network). Folio→Access carries tables, rows, keys, unique/required and relationships, not queries/forms/reports.
- UI text: wrap in `_()`/`N_()`, add Russian and Italian to `presentation/locales/ru.py` and `it.py` (`tests/test_i18n.py`). Domain/application error messages are fixed strings, translated by the UI via `_(str(e))`.
- Tests that build many windows get slow when the theme switches (each window leaves connections behind): keep the dark-theme test first in `test_ui.py`.
- Releases: bump `__version__`, add a CHANGELOG section and a metainfo `<release>`, tag `vX.Y.Z`; CI publishes the .deb and setup .exe. Asset names: `folio_<v>_<arch>.deb`, `Folio-<v>-windows-x64-setup.exe`.

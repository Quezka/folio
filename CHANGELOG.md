# Changelog

## [0.3.3] - 2026-10-26

The interface size set to Automatic is a compact 85% now (the shared toolkit's new standard; 80% and 90% are new choices). Larger sizes stay in Settings.

## [0.3.2] - 2026-10-26

- The interface size set to Automatic is the system's own size again (100%); the shared toolkit had made it 115%, which was too big. Larger sizes stay one choice away in Settings.

## [0.3.1] - 2026-10-26

- The look now comes from the suite's shared toolkit (Folio's comfortable palette is the suite's now); no visible change.

## [0.3.0] - 2026-10-20
- Access files are now opened and edited *in place*, no conversion: open an `.accdb` / `.mdb`
  (or create a new `.accdb` from New database) and every edit, new row, delete and undo goes
  straight into the file. Add fields, tables and links; Folio's own saved queries, forms and
  reports are kept inside the file in a hidden table. A safety copy
  (`name.folio-backup.accdb`) is made before the first change, and files that are open in
  Microsoft Access are never touched. Existing fields and tables can't be renamed, retyped or
  deleted from Folio (the Access library can't do that); converting to `.folio` is still there.

## [0.2.0] - 2026-10-20
- Currency: a real "Currency" field type (€, $, £, CHF, ₽, ¥, zł) shown as money in the datasheet,
  forms, query results and reports, and typed the way people write it (`1.234,50`, `€ 12,50`).
  Access currency columns and CSV amounts with a currency sign become money fields.
- Access import: relationships the file never declared are inferred from column names and data
  (`ID_Negozio` → `Negozi`, `CF` → `Persone`).
- A more comfortable datasheet: Enter moves down, columns fit their contents and remember their
  width, Ctrl+wheel / Ctrl+± zoom, tooltips for cut-off text, sum and average of the selected
  numbers, dates in the local style, and the cursor stays put when a value changes.
- Easier to see: larger default text and "Automatic" size (115%, up to 200%), darker text and
  firmer borders, bold column headers, and a High contrast option in Settings.

## [0.1.0] - 2026-10-20
- First release: tables in a datasheet (typed columns, lookups, search, sort, undo), a table
  designer, visual queries with live SQL, forms, grouped reports with PDF export, a
  relationships diagram, and CSV import/export. Everything lives in one SQLite file.
- Microsoft Access: open `.accdb` / `.mdb` files (tables, rows, keys, relationships) and export
  your database to a new `.accdb`, through a bundled Jackcess helper.

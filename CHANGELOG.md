# Changelog

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

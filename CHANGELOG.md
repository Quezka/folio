# Changelog

## [0.8.0] - 2026-11-09

Real transparency and corners that line up (suite-kit 0.10).

- **See-through windows**: where the desktop can blur what's behind a window, the main window and dialogs let it show
  through, like Windows Aero or macOS sidebars; cards stay solid. On Windows it's the system's Acrylic. On GNOME it
  needs the Blur my Shell extension (the app adds itself to its list). Switch it in Settings, Look.
- **Corners line up**: the sidebar, cards and the Settings list share one radius and one gap, and what's inside them is
  rounded to match, so the curves run side by side. The Settings header floats over the cards, as wide as them.
- The glass look's description in Settings says what it really does now.

## [0.7.0] - 2026-11-08

### Changed
- **Liquid glass done properly, the Apple way.** Backgrounds are plain again and content stays solid; the chrome is glass. Menus, drop-down lists and tooltips blur what's really under them, settings headers float over their cards and blur them as they scroll, and the sidebar floats as an inset panel. On Windows 11 the window shows the system's Mica behind the sidebar. The colour wash is gone.

## [0.6.0] - 2026-11-08

### Changed
- **A glass look on top of Material 3, with brighter colours:** frosted, see-through surfaces over a soft wash of colour. Settings turns it off; High contrast stays solid.
- **Settings is redone in the suite's new window:** sections on the left, cards of rows with switches, nothing cut off on a small screen. Every other window gets its title on top and a filled Save button.

## [0.5.0] - 2026-11-04

### Changed
- The icons are Material Symbols now: outlined, and filled for what is selected.

## [0.4.0] - 2026-11-04

### Changed
- A new look: Material 3 shapes and tonal colours, and the Manrope typeface. A flick on a trackpad now keeps gliding; a mouse wheel works as before.

## [0.3.6] - 2026-11-04

Fixed: changing the interface size and pressing Restart now works, and a button's menu opens exactly under the button (kit 0.5.3).

## [0.3.5] - 2026-10-27

Fixed: the compact text size now reaches labels, buttons, menus and lists too (the desktop theme was keeping them at the system's larger size), so the whole interface really is smaller.

## [0.3.4] - 2026-10-27

The interface is compact: smaller text (never above 9 pt), tighter spacing and smaller icons and panels, instead of the zoom the size setting used to apply. "Automatic" size is 100% again.

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

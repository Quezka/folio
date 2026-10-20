# Microsoft Access files

Folio opens, edits and creates `.accdb` (Access 2010+) and `.mdb` (Access 2000) files with a small
Java helper, `FolioAccess.jar`, built on [Jackcess](https://jackcess.sourceforge.io/)
(Apache-2.0). Access itself is not needed.

## Editing in place (the normal way)

*Open…* (or *Home → Access file…*, or `folio file.accdb`) opens the file where it is; *New database*
can create a new `.accdb`. Everything works as on a `.folio` file (datasheet, queries, forms,
reports, relationships, CSV import, undo) and every change goes into the file at once.

How it works: the helper (`serve` mode) keeps the file open; Folio loads the tables into an
in-memory SQLite mirror that queries and search run on, applies each change to the mirror and then
to the file, and rolls the mirror back (or reloads it) if Access refuses. Large files take a moment
to load because every row is read at open.

What you can do: edit, add and delete rows; add fields; add tables; add links (relationships);
save Folio queries, forms and reports (kept in a hidden `USys_FolioObjects` table inside the file,
Access's own queries/forms/macros are left alone).

What you can't (Jackcess can't): rename, retype or remove existing fields, delete tables,
remove relationships, compact. Folio says so instead of trying. Deleting a parent row that has
related rows is blocked (Access's cascade options aren't applied from Folio).

Safety: before the first change a copy `name.folio-backup.accdb` is made next to the file; a file
with an Access lock file (`.laccdb` / `.ldb`) is refused, because Access has it open.

## Converting

*More → Convert an Access file to Folio…* makes a `.folio` copy (undeclared links are guessed from
column names and data). *More → Export to Access…* writes a new `.accdb` from a `.folio` database.
Pictures, attachments and OLE columns can't be carried over.

## Java

The .deb depends on `default-jre-headless`; the Windows installer bundles a small runtime (jlink).
From source, any Java 11+ on the PATH (or `JAVA_HOME`) works.

## Building

`python scripts/fetch_jackcess.py` downloads the pinned jars (SHA-256 checked),
`python scripts/build_java.py` makes `build/java/FolioAccess.jar`; `scripts/build.py` does both.

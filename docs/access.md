# Microsoft Access files

Folio reads and creates `.accdb` (Access 2010+) and `.mdb` (Access 2000) files with a small Java
helper, `FolioAccess.jar`, built on [Jackcess](https://jackcess.sourceforge.io/) (Apache-2.0).
Access itself is not needed.

**Open / bring in**: *Home → From Access…*, *Open…* on an Access file, or `folio file.accdb`.
Every user table becomes a table of a new `.folio` file; keys, unique and required flags,
autonumbers and relationships (with cascade deletes) are kept. Pictures, attachments and OLE
columns are left out, and the result says so. Access queries, forms and reports aren't carried over.

**Export**: *More → Export to Access…* writes a new Access file with every table, its rows, keys,
unique/required flags and relationships. Saved queries, forms and reports stay in the Folio file.
Folio text longer than 255 characters becomes a Memo field; whole numbers beyond 32 bits become
Double (Access whole numbers are 32-bit). An existing file is never overwritten.

**Java**: the .deb depends on `default-jre-headless`; the Windows installer bundles a small
runtime (made with jlink). From source, any Java 11+ on the PATH (or `JAVA_HOME`) works.

**Building**: `python scripts/fetch_jackcess.py` downloads the pinned jars (SHA-256 checked),
`python scripts/build_java.py` makes `build/java/FolioAccess.jar`; `scripts/build.py` does both.

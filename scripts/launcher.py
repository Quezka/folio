"""Entry script for frozen builds (PyInstaller needs a file, not a module)."""
from folio.app import main

raise SystemExit(main())

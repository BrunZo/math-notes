import os
from pathlib import Path

NOTES_DIR    = Path(os.environ.get("NOTES_DIR", "/srv/notes"))
INBOX_DIR    = NOTES_DIR / "inbox"
OUTPUT_DIR   = NOTES_DIR / "output"
TEX_BUGS_DIR = OUTPUT_DIR / "bugs"
DB_PATH      = NOTES_DIR / "ir.db"
PATCHES_DIR  = OUTPUT_DIR / "patches"

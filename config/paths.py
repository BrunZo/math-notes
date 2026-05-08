import os
from pathlib import Path

NOTES_DIR = Path(os.environ.get("NOTES_DIR", "/srv/notes"))
INBOX_DIR = NOTES_DIR / "inbox"
PENDING_DIR = NOTES_DIR / "pending"
TEX_DIR = NOTES_DIR / "tex"
MANUAL_REVIEW_DIR = NOTES_DIR / "manual_review"
DB_PATH = NOTES_DIR / "ir.db"
PATCHES_DIR = NOTES_DIR / "patches"

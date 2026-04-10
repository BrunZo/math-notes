"""SQLite schema for the intermediate representation (IR)."""
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id            INTEGER PRIMARY KEY,
    path          TEXT    UNIQUE NOT NULL,
    sha256        TEXT,
    last_built_at TEXT
);

CREATE TABLE IF NOT EXISTS sections (
    id                INTEGER PRIMARY KEY,
    file_id           INTEGER NOT NULL REFERENCES files(id),
    parent_section_id INTEGER REFERENCES sections(id),
    level             TEXT    NOT NULL,  -- chapter, section, subsection
    title             TEXT,
    label             TEXT,
    line_start        INTEGER,
    line_end          INTEGER,
    word_count        INTEGER,
    status            TEXT    -- stub, draft, complete
);

CREATE TABLE IF NOT EXISTS objects (
    id         INTEGER PRIMARY KEY,
    file_id    INTEGER NOT NULL REFERENCES files(id),
    section_id INTEGER REFERENCES sections(id),
    kind       TEXT    NOT NULL,  -- theorem, definition, proposition, ...
    label      TEXT,
    title      TEXT,
    line_start INTEGER,
    line_end   INTEGER,
    body_hash  TEXT
);

CREATE TABLE IF NOT EXISTS refs (
    id             INTEGER PRIMARY KEY,
    from_object_id INTEGER REFERENCES objects(id),
    to_label       TEXT    NOT NULL,
    line           INTEGER,
    kind           TEXT    -- ref, eqref, cite, cref
);

CREATE TABLE IF NOT EXISTS sources (
    object_id  INTEGER REFERENCES objects(id),
    scan_path  TEXT,
    scan_sha256 TEXT
);

CREATE TABLE IF NOT EXISTS tags (
    object_id INTEGER REFERENCES objects(id),
    tag       TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sections_file   ON sections(file_id);
CREATE INDEX IF NOT EXISTS idx_objects_file    ON objects(file_id);
CREATE INDEX IF NOT EXISTS idx_objects_section ON objects(section_id);
CREATE INDEX IF NOT EXISTS idx_refs_from       ON refs(from_object_id);
CREATE INDEX IF NOT EXISTS idx_refs_to_label   ON refs(to_label);
CREATE INDEX IF NOT EXISTS idx_tags_object     ON tags(object_id);
"""


def init_db(db_path: Path) -> sqlite3.Connection:
    """Create tables if needed and return a WAL-mode connection."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn

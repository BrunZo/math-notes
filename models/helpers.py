"""Database helpers: CRUD operations and IR queries."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone


# ── Data structures for parsed .tex content ──────────────────────────────────

@dataclass
class SectionInfo:
    level: str            # chapter, section, subsection
    title: str
    label: str | None = None
    line_start: int = 0
    line_end: int = 0
    word_count: int = 0
    status: str = "stub"  # stub (<50 words), draft (<200), complete
    parent_index: int | None = None  # index into the sections list


@dataclass
class ObjectInfo:
    kind: str             # theorem, definition, proposition, ...
    label: str | None = None
    title: str | None = None
    line_start: int = 0
    line_end: int = 0
    body_hash: str = ""
    section_index: int | None = None  # index into the sections list


@dataclass
class RefInfo:
    from_object_index: int | None  # index into the objects list
    to_label: str
    line: int = 0
    kind: str = "ref"     # ref, eqref, cite, cref


@dataclass
class FileParseResult:
    """Complete parse result for a single .tex file."""
    sections: list[SectionInfo] = field(default_factory=list)
    objects: list[ObjectInfo] = field(default_factory=list)
    refs: list[RefInfo] = field(default_factory=list)


# ── Write operations ─────────────────────────────────────────────────────────

def upsert_file(conn: sqlite3.Connection, path: str, sha256: str | None = None) -> int:
    """Insert or update a file record; return its id."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO files (path, sha256, last_built_at) VALUES (?, ?, ?)"
        " ON CONFLICT(path) DO UPDATE SET sha256=excluded.sha256, last_built_at=excluded.last_built_at",
        (path, sha256, now),
    )
    row = conn.execute("SELECT id FROM files WHERE path = ?", (path,)).fetchone()
    return row[0]


def rebuild_file(
    conn: sqlite3.Connection,
    file_path: str,
    result: FileParseResult,
    sha256: str | None = None,
) -> None:
    """Atomically replace all IR data for a single file."""
    file_id = upsert_file(conn, file_path, sha256)

    # Clear old data for this file.
    conn.execute("DELETE FROM refs WHERE from_object_id IN (SELECT id FROM objects WHERE file_id = ?)", (file_id,))
    conn.execute("DELETE FROM sources WHERE object_id IN (SELECT id FROM objects WHERE file_id = ?)", (file_id,))
    conn.execute("DELETE FROM tags WHERE object_id IN (SELECT id FROM objects WHERE file_id = ?)", (file_id,))
    conn.execute("DELETE FROM objects WHERE file_id = ?", (file_id,))
    conn.execute("DELETE FROM sections WHERE file_id = ?", (file_id,))

    # Insert sections; track db ids by list index.
    section_ids: dict[int, int] = {}
    for i, s in enumerate(result.sections):
        parent_db_id = section_ids.get(s.parent_index) if s.parent_index is not None else None
        cur = conn.execute(
            "INSERT INTO sections (file_id, parent_section_id, level, title, label, line_start, line_end, word_count, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (file_id, parent_db_id, s.level, s.title, s.label, s.line_start, s.line_end, s.word_count, s.status),
        )
        section_ids[i] = cur.lastrowid

    # Insert objects; track db ids by list index.
    object_ids: dict[int, int] = {}
    for i, o in enumerate(result.objects):
        section_db_id = section_ids.get(o.section_index) if o.section_index is not None else None
        cur = conn.execute(
            "INSERT INTO objects (file_id, section_id, kind, label, title, line_start, line_end, body_hash)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (file_id, section_db_id, o.kind, o.label, o.title, o.line_start, o.line_end, o.body_hash),
        )
        object_ids[i] = cur.lastrowid

    # Insert refs.
    for r in result.refs:
        from_db_id = object_ids.get(r.from_object_index) if r.from_object_index is not None else None
        conn.execute(
            "INSERT INTO refs (from_object_id, to_label, line, kind) VALUES (?, ?, ?, ?)",
            (from_db_id, r.to_label, r.line, r.kind),
        )

    conn.commit()


# ── Read queries ─────────────────────────────────────────────────────────────

def find_stubs(conn: sqlite3.Connection) -> list[dict]:
    """Return sections that are stubs (word_count < 50 or status = 'stub')."""
    rows = conn.execute(
        "SELECT s.id, s.title, s.level, s.word_count, f.path"
        " FROM sections s JOIN files f ON s.file_id = f.id"
        " WHERE s.status = 'stub'"
        " ORDER BY f.path, s.line_start"
    ).fetchall()
    return [{"id": r[0], "title": r[1], "level": r[2], "word_count": r[3], "file": r[4]} for r in rows]


def find_dangling_refs(conn: sqlite3.Connection) -> list[dict]:
    """Return refs whose to_label doesn't match any object or section label."""
    rows = conn.execute(
        "SELECT r.id, r.to_label, r.line, r.kind, f.path"
        " FROM refs r"
        " LEFT JOIN objects o_from ON r.from_object_id = o_from.id"
        " LEFT JOIN files f ON o_from.file_id = f.id"
        " WHERE r.to_label NOT IN (SELECT label FROM objects WHERE label IS NOT NULL)"
        "   AND r.to_label NOT IN (SELECT label FROM sections WHERE label IS NOT NULL)"
        " ORDER BY f.path, r.line"
    ).fetchall()
    return [{"id": r[0], "to_label": r[1], "line": r[2], "kind": r[3], "file": r[4]} for r in rows]


def find_orphan_labels(conn: sqlite3.Connection) -> list[dict]:
    """Return objects/sections with labels that are never referenced."""
    rows = conn.execute(
        "SELECT o.id, o.kind, o.label, o.title, f.path"
        " FROM objects o JOIN files f ON o.file_id = f.id"
        " WHERE o.label IS NOT NULL"
        "   AND o.label NOT IN (SELECT to_label FROM refs)"
        " ORDER BY f.path, o.line_start"
    ).fetchall()
    return [{"id": r[0], "kind": r[1], "label": r[2], "title": r[3], "file": r[4]} for r in rows]


def get_dependency_graph(conn: sqlite3.Connection) -> list[dict]:
    """Return edges of the dependency graph: object → referenced label."""
    rows = conn.execute(
        "SELECT o.label, o.kind, o.title, r.to_label, r.kind, f.path"
        " FROM refs r"
        " JOIN objects o ON r.from_object_id = o.id"
        " JOIN files f ON o.file_id = f.id"
        " WHERE o.label IS NOT NULL"
        " ORDER BY f.path, o.line_start"
    ).fetchall()
    return [
        {"from_label": r[0], "from_kind": r[1], "from_title": r[2],
         "to_label": r[3], "ref_kind": r[4], "file": r[5]}
        for r in rows
    ]

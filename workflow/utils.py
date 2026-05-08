"""Shared utility functions for workflow workers."""
from pathlib import Path


def glob_finder(directory: Path, pattern: str) -> Path | None:
    """Return the first file matching *pattern* in *directory*, or None."""
    if not directory.exists():
        return None
    return next((f for f in sorted(directory.rglob(pattern))), None)


def stale_tex_finder(output_dir: Path) -> Path | None:
    """Return the first .tex file whose IR entry is missing or stale, or None."""
    from config.paths import DB_PATH
    from models.schema import init_db

    if not output_dir.exists():
        return None
    conn = init_db(DB_PATH)
    try:
        for tex_path in sorted(output_dir.rglob("*.tex")):
            rel = tex_path.relative_to(output_dir).as_posix()
            row = conn.execute(
                "SELECT last_built_at FROM files WHERE path = ?", (rel,)
            ).fetchone()
            if row is None:
                return tex_path
            from datetime import datetime, timezone
            built = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
            mtime = datetime.fromtimestamp(tex_path.stat().st_mtime, tz=timezone.utc)
            if mtime > built:
                return tex_path
    finally:
        conn.close()
    return None

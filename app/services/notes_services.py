from pathlib import Path

from app.helpers.fs_helpers import relative_paths_with_suffix
from app.helpers.notes_helpers import (
    compile_note_pdf,
    extract_chapter_snippet,
    read_note_tex,
)
from config.paths import TEX_DIR

_DASHBOARD_HTML = (
    Path(__file__).parent.parent.parent / "templates" / "notes_dashboard.html"
)


def serve_dashboard() -> str:
    return _DASHBOARD_HTML.read_text()


def list_notes() -> list[dict]:
    notes = [
        {"id": p, "snippet": extract_chapter_snippet(TEX_DIR / f"{p}.tex")}
        for p in relative_paths_with_suffix(TEX_DIR, ".tex")
    ]
    courses = sorted({n["id"].split("/")[0] for n in notes})
    masters = [{"id": f"{c}/master", "snippet": ""} for c in courses]
    return notes + masters


def get_note(path: str) -> tuple[bytes | str, str]:
    p = Path(path)
    if p.suffix == ".tex":
        return read_note_tex(p), "text/plain"
    return compile_note_pdf(p), "application/pdf"

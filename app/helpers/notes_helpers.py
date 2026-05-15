from pathlib import Path

from fastapi import HTTPException

from config.paths import TEX_DIR
from latex import compile as latex


def extract_chapter_snippet(tex_path: Path, max_chars: int = 220) -> str:
    collecting = False
    parts: list[str] = []
    for line in tex_path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("\\chapter"):
            collecting = True
            continue
        if not collecting:
            continue
        if not s:
            if parts:
                break
            continue
        if s.startswith("\\"):
            if parts:
                break
            continue
        parts.append(s)
        if sum(len(p) for p in parts) >= max_chars:
            break
    text = " ".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "…"
    return text


def read_note_tex(note_path: Path) -> str:
    tex_path = TEX_DIR / note_path.parent / f"{note_path.stem}.tex"
    if not tex_path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return tex_path.read_text(encoding="utf-8")


def compile_note_pdf(note_path: Path) -> bytes:
    parent_dir = TEX_DIR / note_path.parent
    if note_path.stem == "master":
        result = latex.compile_master(parent_dir)
    else:
        tex_path = parent_dir / f"{note_path.stem}.tex"
        if not tex_path.exists():
            raise HTTPException(status_code=404, detail="Not found")
        result = latex.compile_single(tex_path)
    if not result.success:
        raise HTTPException(status_code=500, detail=result.stderr)
    if result.pdf_bytes is None:
        raise HTTPException(status_code=404, detail="Not found")
    return result.pdf_bytes

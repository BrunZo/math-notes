import json
from pathlib import Path

import fitz  # pymupdf
from fastapi import UploadFile

from workflow.ingestion.extractors import has_text_layer

ALLOWED_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".webp",
    ".pdf",
    ".txt", ".md", ".docx",
}
FIDELITY_VALUES = {"conservative", "standard"}


def rasterize_pdf(
    raw: bytes, dest_dir: Path, stem: str, start_page: int
) -> tuple[list[str], int]:
    saved: list[str] = []
    page = start_page
    pdf_doc = fitz.open(stream=raw, filetype="pdf")
    for pdf_page in pdf_doc:
        pix = pdf_page.get_pixmap(dpi=200)
        dest = dest_dir / f"{stem}_{page:02d}.png"
        dest.write_bytes(pix.tobytes("png"))
        saved.append(dest.name)
        page += 1
    return saved, page


async def save_uploaded_files(
    files: list[UploadFile], inbox_dir: Path, stem: str
) -> list[str]:
    saved: list[str] = []
    page = 1
    for f in files:
        raw = await f.read()
        suffix = Path(f.filename or "").suffix.lower()
        if suffix == ".pdf" and not has_text_layer(raw):
            new_saved, page = rasterize_pdf(raw, inbox_dir, stem, page)
            saved.extend(new_saved)
        else:
            dest = inbox_dir / f"{stem}_{page:02d}{suffix}"
            dest.write_bytes(raw)
            saved.append(dest.name)
            page += 1
    return saved


def write_job_descriptor(
    inbox_dir: Path, stem: str, model: str, fidelity: str, files: list[str]
) -> None:
    (inbox_dir / f"{stem}.job").write_text(
        json.dumps(
            {"model": model, "fidelity": fidelity, "files": sorted(files)}
        ),
        encoding="utf-8",
    )

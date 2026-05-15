import json
from pathlib import Path

import fitz  # pymupdf
from fastapi import UploadFile

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
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
        if f.content_type == "application/pdf":
            new_saved, page = rasterize_pdf(raw, inbox_dir, stem, page)
            saved.extend(new_saved)
        else:
            suffix = Path(f.filename).suffix.lower() if f.filename else ".jpg"
            dest = inbox_dir / f"{stem}_{page:02d}{suffix}"
            dest.write_bytes(raw)
            saved.append(dest.name)
            page += 1
    return saved


def write_job_descriptor(
    inbox_dir: Path, stem: str, model: str, fidelity: str, images: list[str]
) -> None:
    (inbox_dir / f"{stem}.job").write_text(
        json.dumps(
            {"model": model, "fidelity": fidelity, "images": sorted(images)}
        ),
        encoding="utf-8",
    )

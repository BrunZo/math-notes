"""Text extraction from non-image inputs (.txt, .md, .docx, .pdf)."""

from pathlib import Path

import fitz


TEXT_SUFFIXES = {".txt", ".md", ".docx", ".pdf"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8")
    if suffix == ".docx":
        import docx
        doc = docx.Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)
    if suffix == ".pdf":
        with fitz.open(str(path)) as pdf:
            return "\n\n".join(page.get_text() for page in pdf)
    raise ValueError(f"Unsupported text extension: {suffix}")


def has_text_layer(pdf_bytes: bytes, min_chars: int = 100) -> bool:
    """True if the PDF carries enough extractable text to skip rasterization."""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        total = sum(len(page.get_text().strip()) for page in pdf)
    return total >= min_chars

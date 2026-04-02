"""Standalone worker process. Run with: python -m app.worker"""
import sys
import time
import logging
from pathlib import Path

from .config import settings
from .parsing import transcribe_images
from . import latex

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [worker] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


def find_pending() -> Path | None:
    """Return the first .batch file found under INBOX_DIR/{course_id}/."""
    if not settings.INBOX_DIR.exists():
        return None
    for course_dir in sorted(settings.INBOX_DIR.iterdir()):
        if not course_dir.is_dir():
            continue
        for f in sorted(course_dir.iterdir()):
            if f.suffix == ".batch":
                return f
    return None


def process(batch_path: Path) -> None:
    course_dir = batch_path.parent
    course_id = course_dir.name
    stem = batch_path.stem  # e.g. "01"
    out_dir = settings.OUTPUT_DIR / course_id
    out_dir.mkdir(parents=True, exist_ok=True)

    image_paths = [
        course_dir / name
        for name in batch_path.read_text().splitlines()
        if name.strip()
    ]
    fidelity_file = batch_path.with_suffix(".fidelity")
    fidelity = fidelity_file.read_text().strip() if fidelity_file.exists() else "standard"

    try:
        body = transcribe_images([str(p) for p in image_paths], fidelity=fidelity)
        (out_dir / f"{stem}.tex").write_text(body, encoding="utf-8")
        for img in image_paths:
            (out_dir / img.name).write_bytes(img.read_bytes())
            img.unlink()
        batch_path.unlink()
        fidelity_file.unlink(missing_ok=True)
        latex.regenerate_master(course_id)
        log.info("Done: %s (%d pages) → %s/%s.tex (fidelity=%s)",
                 stem, len(image_paths), course_id, stem, fidelity)
    except Exception as exc:
        (out_dir / f"{stem}.error").write_text(str(exc), encoding="utf-8")
        for img in image_paths:
            img.unlink(missing_ok=True)
        batch_path.unlink(missing_ok=True)
        fidelity_file.unlink(missing_ok=True)
        log.error("Error processing %s: %s", stem, exc)


def main() -> None:
    log.info("Worker started")
    try:
        while True:
            batch = find_pending()
            if batch is None:
                time.sleep(5)
                continue
            log.info("Processing %s", batch)
            process(batch)
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Worker shutting down")
        sys.exit(0)


if __name__ == "__main__":
    main()

"""Standalone worker process. Run with: python -m workflow.worker"""
import json
import logging
import os
import sys
import time
from pathlib import Path

from .parsing import transcribe_images

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [worker] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


def find_job(inbox_dir: Path) -> Path | None:
    """Return the first .job file found (recursively) under inbox_dir."""
    if not inbox_dir.exists():
        return None
    return next(
        (f for f in sorted(inbox_dir.rglob("*.job"))),
        None,
    )


def process(job_path: Path, output_dir: Path) -> None:
    """Process a single .job file.

    Images listed in the job are resolved relative to job_path's directory.
    Compiled .tex and copied images are written to output_dir.
    """
    stem = job_path.stem
    input_dir = job_path.parent

    config = json.loads(job_path.read_text(encoding="utf-8"))
    image_names: list[str] = config.get("images", [])
    image_paths = [input_dir / name for name in image_names]

    def _clean_inbox():
        for img in image_paths:
            img.unlink(missing_ok=True)
        job_path.unlink(missing_ok=True)

    model = config.get("model", None)
    if not model:
        log.error("Error processing %s: Jobs must specify model.", stem)
        _clean_inbox()
        return

    fidelity = config.get("fidelity", "standard")

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        body = transcribe_images([str(p) for p in image_paths], model=model, fidelity=fidelity)
        (output_dir / f"{stem}.tex").write_text(body, encoding="utf-8")
        for img in image_paths:
            (output_dir / img.name).write_bytes(img.read_bytes())
        _clean_inbox()
        log.info("Done: %s (%d pages) → %s/%s.tex (model=%s, fidelity=%s)",
                 stem, len(image_paths), output_dir.name, stem, model, fidelity)
    except Exception as exc:
        (output_dir / f"{stem}.error").write_text(str(exc), encoding="utf-8")
        _clean_inbox()
        log.error("Error processing %s: %s", stem, exc)


def main() -> None:
    inbox_dir = Path(os.environ["INBOX_DIR"])
    output_dir = Path(os.environ["OUTPUT_DIR"])
    log.info("Worker started (inbox=%s, output=%s)", inbox_dir, output_dir)
    try:
        while True:
            job = find_job(inbox_dir)
            if job is None:
                time.sleep(5)
                continue
            log.info("Processing %s", job)
            subdir = job.relative_to(inbox_dir).parent
            process(job, output_dir / subdir)
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Worker shutting down")
        sys.exit(0)


if __name__ == "__main__":
    main()

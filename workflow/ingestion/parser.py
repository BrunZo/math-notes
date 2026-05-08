"""Parser worker: transcribes images to LaTeX via AI and writes to PENDING_DIR."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from config.paths import INBOX_DIR, PENDING_DIR
from llm import MODEL_REGISTRY
from workflow.base import Worker, setup_logging
from workflow.ingestion.config import build_prompt
from workflow.ingestion.preprocessing import preprocess_all
from workflow.utils import glob_finder

log = setup_logging("parser")


def main() -> None:
    Worker(
        name="parser",
        find_job=lambda: glob_finder(INBOX_DIR, "*.job"),
        process=parser_process(INBOX_DIR, PENDING_DIR),
    ).run()


def parser_process(inbox_dir: Path, pending_dir: Path) -> Callable[[Path], None]:
    def process(job_path: Path) -> None:
        stem = job_path.stem
        input_dir = job_path.parent

        config = json.loads(job_path.read_text(encoding="utf-8"))
        image_names: list[str] = config.get("images", [])
        image_paths = [input_dir / name for name in image_names]
        model = config.get("model")
        fidelity = config.get("fidelity", "standard")

        subdir = job_path.relative_to(inbox_dir).parent
        out_dir = pending_dir / subdir
        out_dir.mkdir(parents=True, exist_ok=True)

        processed_paths: list[Path] = []
        try:
            processed_paths = preprocess_all(image_paths)
            body = transcribe_images(
                [str(p) for p in processed_paths], model=model, fidelity=fidelity
            )
            header = provenance_header(image_paths, model)

            out_tex = (out_dir / stem).with_suffix(".tex")
            out_tex.write_text(f"{header}\n{body}", encoding="utf-8")
            log.info(
                "done: %s (%d pages) → %s (model=%s, fidelity=%s)",
                stem,
                len(image_paths),
                out_tex.relative_to(pending_dir),
                model,
                fidelity,
            )
        except Exception as exc:
            out_error = (out_dir / stem).with_suffix(".error")
            out_error.write_text(str(exc), encoding="utf-8")
            log.error("failed %s: %s", stem, exc)

        for img in set(processed_paths + image_paths):
            img.unlink(missing_ok=True)
        job_path.unlink(missing_ok=True)

        # Remove empty subdirectories up to inbox root
        d = input_dir
        while d != inbox_dir:
            try:
                d.rmdir()  # only succeeds if empty
            except OSError:
                break
            d = d.parent

    return process


def transcribe_images(
    image_paths: list[str], model: str, fidelity: str = "standard"
) -> str:
    cls = MODEL_REGISTRY.get(model)
    if cls is None:
        raise ValueError(f"Unknown model '{model}'. Available: {list(MODEL_REGISTRY)}")
    return cls().send_prompt(
        model, build_prompt(fidelity), [Path(p) for p in image_paths]
    )


def provenance_header(source_paths: list[Path], model: str) -> str:
    """Return a LaTeX comment block with source file provenance."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = []
    for p in source_paths:
        sha = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        lines.append(
            f"% source: {p.name}, sha256:{sha}, extracted: {now}, model: {model}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    main()

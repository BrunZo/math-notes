"""Parser worker: transcribes images and/or text inputs to LaTeX via AI."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from config.paths import INBOX_DIR, PENDING_DIR
from llm import OpenRouterClient, list_models
from workflow.base import Worker, setup_logging
from workflow.ingestion.config import build_prompt
from workflow.ingestion.extractors import IMAGE_SUFFIXES, TEXT_SUFFIXES, extract_text
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
        file_names: list[str] = config.get("files", [])
        file_paths = [input_dir / name for name in file_names]
        model = config.get("model")
        fidelity = config.get("fidelity", "standard")

        image_paths = [p for p in file_paths if p.suffix.lower() in IMAGE_SUFFIXES]
        text_paths = [p for p in file_paths if p.suffix.lower() in TEXT_SUFFIXES]

        subdir = job_path.relative_to(inbox_dir).parent
        out_dir = pending_dir / subdir
        out_dir.mkdir(parents=True, exist_ok=True)

        processed_images: list[Path] = []
        try:
            processed_images = preprocess_all(image_paths)
            texts = [extract_text(p) for p in text_paths]
            body = transcribe(
                images=processed_images,
                texts=texts,
                model=model,
                fidelity=fidelity,
            )
            header = provenance_header(file_paths, model)

            out_tex = (out_dir / stem).with_suffix(".tex")
            out_tex.write_text(f"{header}\n{body}", encoding="utf-8")
            log.info(
                "done: %s (%d images, %d texts) → %s (model=%s, fidelity=%s)",
                stem,
                len(image_paths),
                len(text_paths),
                out_tex.relative_to(pending_dir),
                model,
                fidelity,
            )
        except Exception as exc:
            out_error = (out_dir / stem).with_suffix(".error")
            out_error.write_text(str(exc), encoding="utf-8")
            log.error("failed %s: %s", stem, exc)

        for p in set(processed_images + file_paths):
            p.unlink(missing_ok=True)
        job_path.unlink(missing_ok=True)

        d = input_dir
        while d != inbox_dir:
            try:
                d.rmdir()
            except OSError:
                break
            d = d.parent

    return process


def transcribe(
    images: list[Path], texts: list[str], model: str, fidelity: str = "standard"
) -> str:
    if model not in list_models():
        raise ValueError(f"Unknown model '{model}'. Available: {list_models()}")
    return OpenRouterClient().send_prompt(
        model, build_prompt(fidelity), media=images, texts=texts
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

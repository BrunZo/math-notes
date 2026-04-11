"""Parser worker: transcribes images to LaTeX and signals the compiler."""
import json
from pathlib import Path
from typing import Callable

from config.paths import INBOX_DIR, OUTPUT_DIR
from workflow.base import Worker, glob_finder, setup_logging
from .parsing import transcribe_images
from .parsing.base import provenance_header
from .preprocessing import preprocess_all

log = setup_logging("parser")


def make_process(inbox_dir: Path, output_dir: Path) -> Callable[[Path], None]:
    def process(job_path: Path) -> None:
        stem = job_path.stem
        input_dir = job_path.parent

        config = json.loads(job_path.read_text(encoding="utf-8"))
        image_names: list[str] = config.get("images", [])
        image_paths = [input_dir / name for name in image_names]

        def _clean_inbox(extra: list[Path] | None = None):
            for img in image_paths:
                img.unlink(missing_ok=True)
            for p in extra or []:
                p.unlink(missing_ok=True)
            job_path.unlink(missing_ok=True)

        model = config.get("model", None)
        if not model:
            log.error("job %s has no model specified", stem)
            _clean_inbox()
            return

        fidelity = config.get("fidelity", "standard")
        debug_model = config.get("debug_model", "")
        debug_iters = config.get("debug_iters", 0)

        subdir = job_path.relative_to(inbox_dir).parent
        out_dir = output_dir / subdir
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            processed_paths = preprocess_all(image_paths)
            # Preprocessed files that differ from originals need cleanup
            extra_files = [p for p in processed_paths if p not in image_paths]

            body = transcribe_images([str(p) for p in processed_paths], model=model, fidelity=fidelity)
            header = provenance_header(image_paths, model)
            (out_dir / f"{stem}.tex").write_text(f"{header}\n{body}", encoding="utf-8")
            for img in processed_paths:
                (out_dir / img.name).write_bytes(img.read_bytes())
            # Signal compiler that this .tex needs compilation.
            tex_job = json.dumps({"debug_model": debug_model, "debug_iters": debug_iters})
            (out_dir / f"{stem}.tex.job").write_text(tex_job, encoding="utf-8")
            _clean_inbox(extra_files)
            log.info("done: %s (%d pages, %d after preprocessing) → %s/%s.tex (model=%s, fidelity=%s)",
                     stem, len(image_paths), len(processed_paths), out_dir.name, stem, model, fidelity)
        except Exception as exc:
            (out_dir / f"{stem}.error").write_text(str(exc), encoding="utf-8")
            _clean_inbox()
            log.error("failed %s: %s", stem, exc)

    return process


def main() -> None:
    Worker(
        name="parser",
        find_job=glob_finder(INBOX_DIR, "*.job"),
        process=make_process(INBOX_DIR, OUTPUT_DIR),
    ).run()


if __name__ == "__main__":
    main()

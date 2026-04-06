"""Parser worker: transcribes images to LaTeX and signals the compiler."""
import json
import os
from pathlib import Path
from typing import Callable

from .base import Worker, setup_logging
from .parsing import transcribe_images

log = setup_logging("parser")


def make_process(inbox_dir: Path, output_dir: Path) -> Callable[[Path], None]:
    def process(job_path: Path) -> None:
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
            log.error("job %s has no model specified", stem)
            _clean_inbox()
            return

        fidelity = config.get("fidelity", "standard")

        subdir = job_path.relative_to(inbox_dir).parent
        out_dir = output_dir / subdir
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            body = transcribe_images([str(p) for p in image_paths], model=model, fidelity=fidelity)
            (out_dir / f"{stem}.tex").write_text(body, encoding="utf-8")
            for img in image_paths:
                (out_dir / img.name).write_bytes(img.read_bytes())
            # Signal compiler that this .tex needs compilation.
            (out_dir / f"{stem}.tex.job").write_text("{}", encoding="utf-8")
            _clean_inbox()
            log.info("done: %s (%d pages) → %s/%s.tex (model=%s, fidelity=%s)",
                     stem, len(image_paths), out_dir.name, stem, model, fidelity)
        except Exception as exc:
            (out_dir / f"{stem}.error").write_text(str(exc), encoding="utf-8")
            _clean_inbox()
            log.error("failed %s: %s", stem, exc)

    return process


def main() -> None:
    inbox_dir = Path(os.environ["INBOX_DIR"])
    output_dir = Path(os.environ["OUTPUT_DIR"])
    Worker(
        name="parser",
        job_dir=inbox_dir,
        output_dir=output_dir,
        process=make_process(inbox_dir, output_dir),
    ).run()


if __name__ == "__main__":
    main()

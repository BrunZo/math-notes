"""Compiler worker: compiles .tex files and reports LaTeX errors as bug jobs."""
import json
import os
from pathlib import Path
from typing import Callable

from app import latex
from .base import Worker, setup_logging

log = setup_logging("compiler")


def make_process(output_dir: Path) -> Callable[[Path], None]:
    def process(job_path: Path) -> None:
        # job_path is a .tex.job file; the .tex lives alongside it.
        tex_path = job_path.with_suffix("")  # strips .job → .tex
        stem = tex_path.stem
        rel = tex_path.relative_to(output_dir)

        job_path.unlink(missing_ok=True)

        if not tex_path.exists():
            log.warning("no .tex found for %s, skipping", job_path)
            return

        try:
            latex.compile_single(tex_path)
            log.info("compiled %s", rel)
        except RuntimeError as exc:
            error_msg = str(exc)
            log.warning("compile failed for %s: %s", rel, error_msg[:120])
            bug_dir = output_dir / "bugs" / rel.parent
            bug_dir.mkdir(parents=True, exist_ok=True)
            bug_data = {"tex_path": rel.as_posix(), "error": error_msg}
            (bug_dir / f"{stem}.bug").write_text(
                json.dumps(bug_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    return process


def main() -> None:
    output_dir = Path(os.environ["OUTPUT_DIR"])
    Worker(
        name="compiler",
        job_dir=output_dir,
        output_dir=output_dir,
        process=make_process(output_dir),
        glob_pattern="*.tex.job",
    ).run()


if __name__ == "__main__":
    main()

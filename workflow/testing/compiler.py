"""Compiler worker: compiles .tex files and reports LaTeX errors as bug jobs."""
import json
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from config.paths import OUTPUT_DIR, TEX_BUGS_DIR
from latex.compile import compile_single
from workflow.base import Worker, glob_finder, setup_logging
from workflow.testing.log_parser import parse_errors, attach_context

log = setup_logging("compiler")


def make_process(output_dir: Path) -> Callable[[Path], None]:
    def process(job_path: Path) -> None:
        # job_path is a .tex.job file; the .tex lives alongside it.
        tex_path = job_path.with_suffix("")  # strips .job → .tex
        stem = tex_path.stem
        rel = tex_path.relative_to(output_dir)

        job_meta = json.loads(job_path.read_text(encoding="utf-8"))
        debug_model = job_meta.get("debug_model", "")
        debug_iters = job_meta.get("debug_iters", 0)
        job_path.unlink(missing_ok=True)

        if not tex_path.exists():
            log.warning("no .tex found for %s, skipping", job_path)
            return

        result = compile_single(tex_path)

        if result.success:
            log.info("compiled %s", rel)
            return

        errors = parse_errors(result.stderr)
        tex_lines = tex_path.read_text(encoding="utf-8").splitlines()
        attach_context(errors, tex_lines)

        log.warning("compile failed for %s: %d error(s)", rel, len(errors))

        bug_dir = TEX_BUGS_DIR / rel.parent
        bug_dir.mkdir(parents=True, exist_ok=True)
        bug_data = {
            "tex_path": rel.as_posix(),
            "errors": [asdict(e) for e in errors],
            "stderr": result.stderr,
            "debug_model": debug_model,
            "debug_iters": debug_iters,
        }
        (bug_dir / f"{stem}.bug").write_text(
            json.dumps(bug_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return process


def main() -> None:
    Worker(
        name="compiler",
        find_job=glob_finder(OUTPUT_DIR, "*.tex.job"),
        process=make_process(OUTPUT_DIR),
    ).run()


if __name__ == "__main__":
    main()

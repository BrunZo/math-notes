"""LaTeX compilation utilities and compiler worker.

Combines the tectonic compilation functions (formerly app/latex.py) with the
compiler worker that watches for .tex.job files (formerly workflow/compiler.py).
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from jinja2 import Environment, FileSystemLoader

from config.paths import OUTPUT_DIR
from workflow.base import Worker, glob_finder, setup_logging

log = setup_logging("compiler")

# ── Compilation helpers ──────────────────────────────────────────────────────

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=False)

_LATEX_SPECIAL = str.maketrans({
    "_": r"\_", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "^": r"\^{}", "{": r"\{", "}": r"\}",
})


def compile(tex_path: Path) -> bytes:
    """Compile a single .tex file and return PDF bytes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        dest = tmp / tex_path.name
        dest.write_text(tex_path.read_text(encoding="utf-8"), encoding="utf-8")
        result = subprocess.run(
            ["tectonic", str(dest)],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr)
        return (tmp / tex_path.with_suffix(".pdf").name).read_bytes()


def compile_single(tex_path: Path) -> bytes:
    """Compile a body-only .tex file by wrapping it in a master document."""
    master_src = _jinja_env.get_template("master.tex.j2").render(
        course_name=tex_path.parent.name.translate(_LATEX_SPECIAL),
        tex_paths=[tex_path.name],
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        shutil.copy2(tex_path, tmp / tex_path.name)
        (tmp / "master.tex").write_text(master_src, encoding="utf-8")
        result = subprocess.run(
            ["tectonic", str(tmp / "master.tex")],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr)
        return (tmp / "master.pdf").read_bytes()


def compile_master(out_dir: Path) -> bytes:
    """Generate a master.tex from all .tex files in out_dir and return compiled PDF bytes."""
    tex_files = sorted(
        (f for f in out_dir.glob("*.tex") if f.name != "master.tex"),
        key=lambda f: f.stem,
    )
    if not tex_files:
        raise RuntimeError(f"No .tex files found in {out_dir}")

    master_src = _jinja_env.get_template("master.tex.j2").render(
        course_name=out_dir.name.translate(_LATEX_SPECIAL),
        tex_paths=[f.name for f in tex_files],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for f in tex_files:
            shutil.copy2(f, tmp / f.name)
        (tmp / "master.tex").write_text(master_src, encoding="utf-8")
        result = subprocess.run(
            ["tectonic", str(tmp / "master.tex")],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr)
        return (tmp / "master.pdf").read_bytes()


# ── Compiler worker ──────────────────────────────────────────────────────────

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

        try:
            compile_single(tex_path)
            log.info("compiled %s", rel)
        except RuntimeError as exc:
            error_msg = str(exc)
            log.warning("compile failed for %s: %s", rel, error_msg[:120])
            bug_dir = output_dir / "bugs" / rel.parent
            bug_dir.mkdir(parents=True, exist_ok=True)
            bug_data = {
                "tex_path": rel.as_posix(), "error": error_msg,
                "debug_model": debug_model, "debug_iters": debug_iters,
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

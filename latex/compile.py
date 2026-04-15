"""LaTeX compilation via tectonic."""

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=False)

_LATEX_SPECIAL = str.maketrans({
    "_": r"\_", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "^": r"\^{}", "{": r"\{", "}": r"\}",
})


@dataclass
class CompileResult:
    success: bool
    pdf_bytes: bytes | None = None
    stderr: str = ""
    line_offset: int = 0


def _run_tectonic(master_src: str) -> CompileResult:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "master.tex").write_text(master_src, encoding="utf-8")
        result = subprocess.run(
            ["tectonic", "-Z", "continue-on-errors", str(tmp / "master.tex")],
            cwd=tmpdir, capture_output=True, text=True,
        )
        pdf_path = tmp / "master.pdf"
        return CompileResult(
            success=result.returncode == 0,
            pdf_bytes=pdf_path.read_bytes() if pdf_path.exists() else None,
            stderr=result.stderr,
        )


def compile_single(tex_path: Path) -> CompileResult:
    """Compile a body-only .tex file by inlining it into a master document."""
    body = tex_path.read_text(encoding="utf-8")
    master_src = _jinja_env.get_template("master.tex.j2").render(
        course_name=tex_path.parent.name.translate(_LATEX_SPECIAL),
        body=body,
    )
    result = _run_tectonic(master_src)
    result.line_offset = master_src.split(body)[0].count("\n")
    return result


def compile_master(out_dir: Path) -> CompileResult:
    """Compile all .tex files in out_dir via \\input in a master document."""
    tex_files = sorted(
        (f for f in out_dir.glob("*.tex") if f.name != "master.tex"),
        key=lambda f: f.stem,
    )
    if not tex_files:
        return CompileResult(success=False, stderr=f"No .tex files found in {out_dir}")

    master_src = _jinja_env.get_template("master.tex.j2").render(
        course_name=out_dir.name.translate(_LATEX_SPECIAL),
        tex_paths=[f.name for f in tex_files],
    )
    # compile_master uses \input, so copy the files into the temp dir
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for f in tex_files:
            shutil.copy2(f, tmp / f.name)
        (tmp / "master.tex").write_text(master_src, encoding="utf-8")
        result = subprocess.run(
            ["tectonic", "-Z", "continue-on-errors", str(tmp / "master.tex")],
            cwd=tmpdir, capture_output=True, text=True,
        )
        pdf_path = tmp / "master.pdf"
        return CompileResult(
            success=result.returncode == 0,
            pdf_bytes=pdf_path.read_bytes() if pdf_path.exists() else None,
            stderr=result.stderr,
        )

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .config import settings

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=False)


_LATEX_SPECIAL = str.maketrans({
    "_": r"\_", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "^": r"\^{}", "{": r"\{", "}": r"\}",
})


def regenerate_master(course_id: str) -> Path:
    out_dir = settings.OUTPUT_DIR / course_id
    tex_files = sorted(
        (f for f in out_dir.glob("*.tex") if f.name != "master.tex"),
        key=lambda f: f.stem,
    )
    template = _jinja_env.get_template("master.tex.j2")
    rendered = template.render(
        course_name=course_id.translate(_LATEX_SPECIAL),
        tex_paths=[f.name for f in tex_files],
    )
    master_path = out_dir / "master.tex"
    master_path.write_text(rendered, encoding="utf-8")
    return master_path


if __name__ == "__main__":
    if sys.argv[1:]:
        courses = sys.argv[1:]
    else:
        courses = [d.name for d in sorted(settings.OUTPUT_DIR.iterdir()) if d.is_dir()]
    for cid in courses:
        path = regenerate_master(cid)
        print(f"  {cid} → {path}")


def compile(tex_path: Path) -> bytes:
    """Compile tex_path in a temp directory and return PDF bytes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for f in tex_path.parent.glob("*.tex"):
            shutil.copy2(f, tmp / f.name)
        result = subprocess.run(
            ["tectonic", str(tmp / tex_path.name)],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr)
        return (tmp / tex_path.with_suffix(".pdf").name).read_bytes()

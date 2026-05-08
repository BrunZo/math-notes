from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_TEMPLATES_DIR = Path(__file__).parent
_jinja_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=False)


def load_preamble() -> str:
    """Extract the preamble (everything before \\begin{document}) from master.tex.j2."""
    template_src = _jinja_env.loader.get_source(_jinja_env, "master.tex.j2")[0]
    lines = template_src.splitlines()
    preamble_lines = []
    for line in lines:
        if r"\begin{document}" in line:
            break
        preamble_lines.append(line)
    return "\n".join(preamble_lines)

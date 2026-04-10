"""Parse tectonic stderr into structured error records."""
import re
from dataclasses import dataclass

# Matches lines like:  error: master.tex:42: Undefined control sequence.
# or:                  error: master.tex:42: ...message...
_RE_ERROR = re.compile(
    r"^error:\s*(?P<file>[^:]+):(?P<line>\d+):\s*(?P<message>.+)$",
    re.MULTILINE,
)


@dataclass
class TexError:
    file: str
    line: int
    message: str
    context: str = ""  # filled in later from .tex source


def parse_errors(stderr: str) -> list[TexError]:
    """Extract structured errors from tectonic stderr output."""
    return [
        TexError(file=m.group("file"), line=int(m.group("line")), message=m.group("message").strip())
        for m in _RE_ERROR.finditer(stderr)
    ]


def attach_context(errors: list[TexError], tex_lines: list[str], context_lines: int = 15) -> None:
    """Attach surrounding .tex context to each error in place."""
    n = len(tex_lines)
    for err in errors:
        idx = err.line - 1  # 0-indexed
        start = max(0, idx - context_lines)
        end = min(n, idx + context_lines + 1)
        numbered = [f"{i + 1:4d}  {tex_lines[i]}" for i in range(start, end)]
        err.context = "\n".join(numbered)

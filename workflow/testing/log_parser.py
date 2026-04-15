"""Parse tectonic stderr into structured error records."""

import re
from dataclasses import dataclass

_RE_ERROR = re.compile(
    r"^error:\s*(?P<file>[^:]+):(?P<line>\d+):\s*(?P<message>.+)$",
    re.MULTILINE,
)


@dataclass
class TexError:
    file: str
    line: int
    message: str


def parse_errors(stderr: str, line_offset: int = 0) -> list[TexError]:
    """Extract structured errors from tectonic stderr output.

    line_offset is subtracted from reported line numbers to map master-document
    lines back to the body file.
    """
    return [
        TexError(
            file=m.group("file"),
            line=max(1, int(m.group("line")) - line_offset),
            message=m.group("message").strip(),
        )
        for m in _RE_ERROR.finditer(stderr)
    ]

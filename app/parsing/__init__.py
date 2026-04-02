from pathlib import Path

from .claude_parser import ClaudeParser

__all__ = ["ClaudeParser", "transcribe_images"]


def transcribe_images(image_paths: list[str], fidelity: str = "standard") -> str:
    parser = ClaudeParser(fidelity=fidelity)
    return parser.parse_images([Path(p) for p in image_paths])

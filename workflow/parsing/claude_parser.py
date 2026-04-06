import base64
from pathlib import Path

import anthropic
import fitz

import os

from .base import BaseParser, build_prompt, media_type

# Anthropic enforces a 5 MB limit on the base64-encoded image string.
# Base64 expands raw bytes by 4/3, so the raw file must stay under 3.75 MB.
_API_ENCODED_LIMIT = 5 * 1024 * 1024
_RAW_LIMIT = _API_ENCODED_LIMIT * 3 // 4  # ~3.93 MB


def _encode_image(path: Path) -> tuple[bytes, str]:
    """Return (raw_bytes, media_type) for an image, compressing if needed."""
    raw = path.read_bytes()
    if len(raw) <= _RAW_LIMIT:
        return raw, media_type(path)

    # Image is too large — re-encode as JPEG at progressively lower quality.
    doc = fitz.open(str(path))
    pix = doc[0].get_pixmap()
    if pix.n not in (1, 3):
        pix = fitz.Pixmap(fitz.csRGB, pix)

    for quality in (85, 70, 55, 40):
        compressed = pix.tobytes("jpeg", jpg_quality=quality)
        if len(compressed) <= _RAW_LIMIT:
            return compressed, "image/jpeg"

    # Still too large — scale down the pixmap and try once more.
    scale = (_RAW_LIMIT / len(raw)) ** 0.5
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(scale, scale))
    if pix.n not in (1, 3):
        pix = fitz.Pixmap(fitz.csRGB, pix)
    return pix.tobytes("jpeg", jpg_quality=40), "image/jpeg"


class ClaudeParser(BaseParser):
    MODELS = [
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
    ]

    def __init__(self, model: str, fidelity: str = "standard"):
        self._client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self._model = model
        self._system_prompt = build_prompt(fidelity)

    def parse_images(self, image_paths: list[Path]) -> str:
        image_paths = [Path(p) for p in image_paths]

        content: list[dict] = []
        for p in image_paths:
            raw, mt = _encode_image(p)
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mt,
                    "data": base64.standard_b64encode(raw).decode(),
                },
            })

        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=8096,
                system=self._system_prompt,
                messages=[{"role": "user", "content": content}],
            )
            return message.content[0].text
        except Exception as exc:
            names = ", ".join(p.name for p in image_paths)
            raise RuntimeError(f"Anthropic API call failed for [{names}]: {exc}") from exc

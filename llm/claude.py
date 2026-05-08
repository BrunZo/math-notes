import base64
import os
from pathlib import Path

import anthropic
import cv2
import fitz

from .base import BaseAIClient, media_type

_API_ENCODED_LIMIT = 5 * 1024 * 1024
_RAW_LIMIT = _API_ENCODED_LIMIT * 3 // 4
_MAX_DIMENSION = 1999


def _cap_dimensions(path: Path) -> Path:
    """Downscale so neither side exceeds _MAX_DIMENSION. Overwrites in place."""
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    h, w = img.shape[:2]
    scale = _MAX_DIMENSION / max(h, w)
    if scale >= 1:
        return path
    img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), img)
    return path


def _encode_image(path: Path) -> tuple[bytes, str]:
    """Return (raw_bytes, media_type) for an image, compressing if needed."""
    raw = path.read_bytes()
    if len(raw) <= _RAW_LIMIT:
        return raw, media_type(path)

    doc = fitz.open(str(path))
    pix = doc[0].get_pixmap()
    if pix.n not in (1, 3):
        pix = fitz.Pixmap(fitz.csRGB, pix)

    for quality in (85, 70, 55, 40):
        compressed = pix.tobytes("jpeg", jpg_quality=quality)
        if len(compressed) <= _RAW_LIMIT:
            return compressed, "image/jpeg"

    scale = (_RAW_LIMIT / len(raw)) ** 0.5
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(scale, scale))
    if pix.n not in (1, 3):
        pix = fitz.Pixmap(fitz.csRGB, pix)
    return pix.tobytes("jpeg", jpg_quality=40), "image/jpeg"


class ClaudeClient(BaseAIClient):
    MODELS = [
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
    ]

    def __init__(self):
        self._client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def send_prompt(self, model: str, prompt: str, media: list[Path]) -> str:
        content: list[dict] = []
        for p in media:
            p = _cap_dimensions(p)
            raw, mt = _encode_image(p)
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mt,
                    "data": base64.standard_b64encode(raw).decode(),
                },
            })
        if not content:
            content = [{"type": "text", "text": prompt}]

        message = self._client.messages.create(
            model=model,
            max_tokens=16384,
            system=prompt,
            messages=[{"role": "user", "content": content}],
        )
        return message.content[0].text

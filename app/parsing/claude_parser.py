import base64
from pathlib import Path

import anthropic

from .base import BaseParser, build_prompt, media_type
from ..config import settings


class ClaudeParser(BaseParser):
    def __init__(self, model: str = "claude-opus-4-6", fidelity: str = "standard"):
        self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._model = model
        self._system_prompt = build_prompt(fidelity)

    def parse_images(self, image_paths: list[Path]) -> str:
        image_paths = [Path(p) for p in image_paths]

        content: list[dict] = []
        for p in image_paths:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type(p),
                    "data": base64.standard_b64encode(p.read_bytes()).decode(),
                },
            })
        n = len(image_paths)
        content.append({
            "type": "text",
            "text": (
                "Transcribe this page to LaTeX."
                if n == 1
                else f"Transcribe all {n} pages to LaTeX. "
                     "Produce a single continuous document body in page order."
            ),
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

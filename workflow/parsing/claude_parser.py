import base64
from pathlib import Path

import anthropic

import os

from .base import BaseParser, build_prompt, media_type


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

        content: list[dict] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type(p),
                    "data": base64.standard_b64encode(p.read_bytes()).decode(),
                },
            }
            for p in image_paths
        ]

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

import os
from pathlib import Path

from google import genai
from google.genai import types

from .base import BaseParser, build_prompt, media_type


class GeminiParser(BaseParser):
    MODELS = [
        "gemini-3.1-pro-preview",
        "gemini-3-flash-preview",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
    ]

    def __init__(self, model: str, fidelity: str = "standard"):
        self._client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        self._model = model
        self._system_prompt = build_prompt(fidelity)

    def parse_images(self, image_paths: list[Path]) -> str:
        image_paths = [Path(p) for p in image_paths]

        parts = [
            types.Part.from_bytes(data=p.read_bytes(), mime_type=media_type(p))
            for p in image_paths
        ]

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=parts,
                config=types.GenerateContentConfig(system_instruction=self._system_prompt),
            )
            return response.text
        except Exception as exc:
            names = ", ".join(p.name for p in image_paths)
            raise RuntimeError(f"Gemini API call failed for [{names}]: {exc}") from exc

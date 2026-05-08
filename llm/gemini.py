import os
from pathlib import Path

from google import genai
from google.genai import types

from .base import BaseAIClient, media_type


class GeminiClient(BaseAIClient):
    MODELS = [
        "gemini-3.1-pro-preview",
        "gemini-3-flash-preview",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
    ]

    def __init__(self):
        self._client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

    def send_prompt(self, model: str, prompt: str, media: list[Path]) -> str:
        if media:
            parts = [
                types.Part.from_bytes(data=p.read_bytes(), mime_type=media_type(p))
                for p in media
            ]
            contents = parts
        else:
            contents = prompt

        try:
            response = self._client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(system_instruction=prompt),
            )
            return response.text
        except Exception as exc:
            names = ", ".join(p.name for p in media) if media else "(text-only)"
            raise RuntimeError(f"Gemini API call failed for [{names}]: {exc}") from exc

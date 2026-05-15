import base64
import os
from functools import lru_cache
from pathlib import Path

from openrouter import OpenRouter


def _media_type(path: Path) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "image/jpeg")


def _client() -> OpenRouter:
    return OpenRouter(api_key=os.environ["OPENROUTER_API_KEY"])


@lru_cache(maxsize=1)
def list_models() -> list[str]:
    """Multimodal models available on OpenRouter (cached for process lifetime)."""
    models = _client().models.list()
    return sorted(
        m.id for m in models.data
        if "image" in (getattr(m.architecture, "input_modalities", None) or [])
    )


class OpenRouterClient:
    def __init__(self):
        self._client = _client()

    def send_prompt(
        self,
        model: str,
        prompt: str,
        media: list[Path] = (),
        texts: list[str] = (),
    ) -> str:
        content: list[dict] = []
        for t in texts:
            content.append({"type": "text", "text": t})
        for p in media:
            b64 = base64.b64encode(p.read_bytes()).decode()
            url = f"data:{_media_type(p)};base64,{b64}"
            content.append({"type": "image_url", "image_url": {"url": url}})
        if not content:
            content = [{"type": "text", "text": prompt}]

        response = self._client.chat.send(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": content},
            ],
        )
        return response.choices[0].message.content

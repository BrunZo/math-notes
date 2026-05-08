from abc import ABC, abstractmethod
from pathlib import Path


class BaseAIClient(ABC):
    @abstractmethod
    def send_prompt(self, model: str, prompt: str, media: list[Path]) -> str:
        ...


def media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "image/jpeg")

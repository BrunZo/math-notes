from pathlib import Path

from .base import BaseAIClient
from .claude_parser import ClaudeParser
from .gemini_parser import GeminiParser

__all__ = ["BaseAIClient", "ClaudeParser", "GeminiParser", "MODELS_BY_PROVIDER", "MODEL_REGISTRY", "transcribe_images"]

# Provider → available model IDs. Single source of truth.
MODELS_BY_PROVIDER: dict[str, list[str]] = {
    "claude": ClaudeParser.MODELS,
    "gemini": GeminiParser.MODELS,
}

# Flat model-ID → parser class, derived from the above.
MODEL_REGISTRY: dict[str, type] = {
    model: cls
    for provider, (cls, models) in {
        "claude": (ClaudeParser, ClaudeParser.MODELS),
        "gemini": (GeminiParser, GeminiParser.MODELS),
    }.items()
    for model in models
}


def transcribe_images(image_paths: list[str], model: str, fidelity: str = "standard") -> str:
    cls = MODEL_REGISTRY.get(model)
    if cls is None:
        raise ValueError(f"Unknown model '{model}'. Available: {list(MODEL_REGISTRY)}")
    return cls(model=model, fidelity=fidelity).parse_images([Path(p) for p in image_paths])

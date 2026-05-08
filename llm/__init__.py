from .base import BaseAIClient
from .claude import ClaudeClient
from .gemini import GeminiClient

__all__ = ["BaseAIClient", "ClaudeClient", "GeminiClient", "MODELS_BY_PROVIDER", "MODEL_REGISTRY"]

# Provider -> available model IDs. Single source of truth.
MODELS_BY_PROVIDER: dict[str, list[str]] = {
    "claude": ClaudeClient.MODELS,
    "gemini": GeminiClient.MODELS,
}

# Flat model-ID -> client class, derived from the above.
MODEL_REGISTRY: dict[str, type] = {
    model: cls
    for cls, models in {
        ClaudeClient: ClaudeClient.MODELS,
        GeminiClient: GeminiClient.MODELS,
    }.items()
    for model in models
}

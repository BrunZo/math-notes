from pathlib import Path

from dotenv import load_dotenv
import os

load_dotenv()


def _require(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(f"Required environment variable '{key}' is missing or empty")
    return val


class Settings:
    SECRET_TOKEN: str = _require("SECRET_TOKEN")
    ANTHROPIC_API_KEY: str = _require("ANTHROPIC_API_KEY")
    OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
    GOOGLE_API_KEY: str = os.environ.get("GOOGLE_API_KEY", "")
    INBOX_DIR: Path = Path(_require("INBOX_DIR"))
    OUTPUT_DIR: Path = Path(_require("OUTPUT_DIR"))


settings = Settings()

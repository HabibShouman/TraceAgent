"""Configuration that never includes API keys in its representation."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
import os


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "gemini-3.8-flash"


class ConfigurationError(ValueError):
    """A local setting needs attention before a network request is made."""


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    model: str = DEFAULT_MODEL

    @classmethod
    def from_mapping(cls, values: Mapping[str, str | None]) -> "Settings":
        gemini_key = (values.get("GEMINI_API_KEY") or "").strip()
        google_key = (values.get("GOOGLE_API_KEY") or "").strip()
        if gemini_key and google_key and gemini_key != google_key:
            raise ConfigurationError(
                "GEMINI_API_KEY and GOOGLE_API_KEY differ. Keep one key configured "
                "so the intended Google project is used."
            )
        key = gemini_key or google_key
        if not key or key.casefold() in {"your_api_key", "your-api-key", "paste_your_key_here"}:
            raise ConfigurationError("Add your existing Gemini API key to the local .env file.")
        model = (values.get("GEMINI_MODEL") or DEFAULT_MODEL).strip().removeprefix("models/")
        if not model or any(character.isspace() for character in model):
            raise ConfigurationError("GEMINI_MODEL must be a model ID, such as gemini-3.8-flash.")
        return cls(api_key=key, model=model)


def load_settings() -> Settings:
    # Read only this project's .env, even when launched from another directory.
    # Shell variables take precedence, as they do in most deployment environments.
    from dotenv import dotenv_values

    file_values = dotenv_values(PROJECT_ROOT / ".env", interpolate=False)
    return Settings.from_mapping({**file_values, **os.environ})

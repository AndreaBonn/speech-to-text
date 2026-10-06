"""User-level LLM/transcription preferences, outside `data_dir` (D3).

`preferences.json` sits beside `credentials.json` in the user config
directory (`config_dir.py`). Resolution order is env > file > default,
mirroring the secret store (D4): a field pinned by `SBOBINA_*` for this
process is not one the UI can change for it, reported as `locked_by_env`.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from sbobina.atomic_json import atomic_write_json
from sbobina.settings import (
    LlmChainEntry,
    Settings,
    TranscriptionEngine,
    validate_llm_chain_entries,
)

logger = logging.getLogger(__name__)

_FILE_MODE = 0o600
_PREFERENCES_FILENAME = "preferences.json"
# D3: only fields that also exist on `Settings` can be pinned by env.
# `cloud_ack`/`cloud_ack_audio` are UI-only consent timestamps.
_ENV_LOCKABLE_FIELDS = (
    "llm_engine",
    "llm_chain",
    "llm_ollama_fallback",
    "transcription_engine",
)


class UserPreferences(BaseModel):
    """Persisted shape of `preferences.json`."""

    model_config = ConfigDict(frozen=True)

    llm_engine: Literal["local", "api"] = "local"
    llm_chain: list[LlmChainEntry] = Field(default_factory=list)
    llm_ollama_fallback: bool = True
    transcription_engine: TranscriptionEngine = "whisper"
    cloud_ack: datetime | None = None
    cloud_ack_audio: datetime | None = None

    @field_validator("llm_chain")
    @classmethod
    def validate_chain(cls, value: list[LlmChainEntry]) -> list[LlmChainEntry]:
        return validate_llm_chain_entries(value)


class ResolvedPreferences(BaseModel):
    """`UserPreferences` plus which fields are pinned by the environment."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    preferences: UserPreferences
    locked_by_env: frozenset[str]


def preferences_path(config_dir: Path) -> Path:
    return config_dir / _PREFERENCES_FILENAME


def _read_file_preferences(path: Path) -> UserPreferences:
    if not path.exists():
        return UserPreferences()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return UserPreferences.model_validate(raw)
    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
        OSError,
        ValidationError,
    ) as error:
        logger.warning(
            "preferences.json illeggibile (%s), uso i valori predefiniti", error
        )
        return UserPreferences()


def _env_locked_fields() -> frozenset[str]:
    # A fresh Settings() sees only env and .env: the `settings` a child
    # rebuilds from a full dump has every field in model_fields_set.
    return frozenset(_ENV_LOCKABLE_FIELDS) & Settings().model_fields_set


def resolve_preferences(settings: Settings, path: Path) -> ResolvedPreferences:
    """Merge `preferences.json` with env overrides (env > file > default)."""
    file_preferences = _read_file_preferences(path)
    locked = _env_locked_fields()
    merged = file_preferences.model_dump()
    for field in locked:
        merged[field] = getattr(settings, field)
    preferences = UserPreferences.model_validate(merged)
    return ResolvedPreferences(preferences=preferences, locked_by_env=locked)


def save_preferences(path: Path, preferences: UserPreferences) -> None:
    atomic_write_json(
        path=path, data=preferences.model_dump(mode="json"), mode=_FILE_MODE
    )


def effective_settings(settings: Settings, config_dir: Path) -> Settings:
    """`settings` with the LLM/transcription fields resolved from preferences."""
    path = preferences_path(config_dir)
    if not path.exists():
        return settings
    resolved = resolve_preferences(settings=settings, path=path)
    return settings.model_copy(
        update={
            "llm_engine": resolved.preferences.llm_engine,
            "llm_chain": resolved.preferences.llm_chain,
            "llm_ollama_fallback": resolved.preferences.llm_ollama_fallback,
            "transcription_engine": resolved.preferences.transcription_engine,
        }
    )

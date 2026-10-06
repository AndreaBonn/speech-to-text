"""Read and change the user's engine, chain and key settings (T034-T035).

Framework-agnostic: the web router validates the HTTP shape and maps the
errors raised here; this module owns the rules (consent before any cloud
engine, env-pinned fields read-only, keys never returned).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import JsonValue

from sbobina.config_dir import resolve_config_dir
from sbobina.credential_store import SECRET_PROVIDERS, CredentialStore, masked_view
from sbobina.runtime_config import runtime_keys
from sbobina.settings import LlmChainEntry, Settings, TranscriptionEngine
from sbobina.user_preferences import (
    ResolvedPreferences,
    UserPreferences,
    preferences_path,
    resolve_preferences,
    save_preferences,
)


class CloudAckRequiredError(Exception):
    """A cloud engine was chosen without confirming that data leaves the PC."""


class LockedByEnvError(Exception):
    """The request changes a field pinned by an `SBOBINA_*` variable."""

    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


@dataclass(frozen=True, kw_only=True)
class LlmUpdate:
    llm_engine: Literal["local", "api"]
    llm_chain: list[LlmChainEntry]
    llm_ollama_fallback: bool
    cloud_ack: bool


@dataclass(frozen=True, kw_only=True)
class TranscriptionUpdate:
    transcription_engine: TranscriptionEngine
    cloud_ack_audio: bool


def _paths(settings: Settings) -> tuple[Path, CredentialStore]:
    config_dir = resolve_config_dir(settings=settings)
    return preferences_path(config_dir), CredentialStore(config_dir=config_dir)


def _resolved(settings: Settings) -> ResolvedPreferences:
    path, _ = _paths(settings=settings)
    return resolve_preferences(settings=settings, path=path)


def _warnings(prefs: UserPreferences, keys: dict[str, str]) -> dict[str, JsonValue]:
    missing: list[JsonValue] = []
    if prefs.llm_engine == "api":
        missing = [e.provider for e in prefs.llm_chain if e.provider not in keys]
    if prefs.transcription_engine == "assemblyai" and "assemblyai" not in keys:
        missing.append("assemblyai")
    return {
        "missing_keys": list(dict.fromkeys(missing)),
        "empty_chain": prefs.llm_engine == "api" and not prefs.llm_chain,
    }


def settings_view(settings: Settings) -> dict[str, JsonValue]:
    """Everything the Settings page shows; key values are never included."""
    resolved = _resolved(settings=settings)
    _, store = _paths(settings=settings)
    prefs = resolved.preferences
    keys_view = _keys_json(settings=settings, store=store)
    return {
        "preferences": prefs.model_dump(mode="json"),
        "locked_by_env": [field for field in sorted(resolved.locked_by_env)],
        "keys": keys_view,
        "warnings": _warnings(prefs=prefs, keys=runtime_keys(settings=settings)),
    }


def _check_locks(resolved: ResolvedPreferences, changes: dict[str, object]) -> None:
    for field in sorted(resolved.locked_by_env):
        if field in changes and changes[field] != getattr(resolved.preferences, field):
            raise LockedByEnvError(field=field)


def _save(settings: Settings, changes: dict[str, object]) -> None:
    resolved = _resolved(settings=settings)
    _check_locks(resolved=resolved, changes=changes)
    path, _ = _paths(settings=settings)
    current = resolved.preferences.model_dump()
    save_preferences(
        path=path, preferences=UserPreferences.model_validate(current | changes)
    )


def update_llm(settings: Settings, update: LlmUpdate) -> None:
    """Save engine and chain; the api engine needs a recorded consent."""
    current = _resolved(settings=settings).preferences
    changes: dict[str, object] = {
        "llm_engine": update.llm_engine,
        "llm_chain": update.llm_chain,
        "llm_ollama_fallback": update.llm_ollama_fallback,
    }
    if update.llm_engine == "api" and current.cloud_ack is None:
        if not update.cloud_ack:
            raise CloudAckRequiredError
        changes["cloud_ack"] = datetime.now(tz=UTC)
    _save(settings=settings, changes=changes)


def update_transcription(settings: Settings, update: TranscriptionUpdate) -> None:
    """Save the transcription engine; AssemblyAI needs its own consent."""
    current = _resolved(settings=settings).preferences
    changes: dict[str, object] = {
        "transcription_engine": update.transcription_engine,
    }
    is_cloud = update.transcription_engine == "assemblyai"
    if is_cloud and current.cloud_ack_audio is None:
        if not update.cloud_ack_audio:
            raise CloudAckRequiredError
        changes["cloud_ack_audio"] = datetime.now(tz=UTC)
    _save(settings=settings, changes=changes)


def is_known_provider(provider: str) -> bool:
    return provider in SECRET_PROVIDERS


def set_key(settings: Settings, provider: str, key: str) -> dict[str, JsonValue]:
    """Store `key` and return only its masked view."""
    _, store = _paths(settings=settings)
    store.set_key(provider=provider, key=key)
    entry = masked_view(settings=settings, store=store)[provider]
    view: dict[str, JsonValue] = {"provider": provider}
    view.update({name: value for name, value in entry.items()})
    return view


def delete_key(settings: Settings, provider: str) -> None:
    _, store = _paths(settings=settings)
    store.delete_key(provider=provider)


def _keys_json(settings: Settings, store: CredentialStore) -> dict[str, JsonValue]:
    view: dict[str, JsonValue] = {}
    for provider, entry in masked_view(settings=settings, store=store).items():
        item: dict[str, JsonValue] = {name: value for name, value in entry.items()}
        view[provider] = item
    return view

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sbobina import settings_service
from sbobina.credential_store import CredentialStore
from sbobina.runtime_config import runtime_settings
from sbobina.settings import Settings
from sbobina.user_preferences import (
    UserPreferences,
    effective_settings,
    resolve_preferences,
    save_preferences,
)


def test_saved_semantic_preferences_reach_effective_settings(tmp_path: Path) -> None:
    preferences = UserPreferences.model_validate(
        {"embedding_model": "custom:latest", "semantic_search": False}
    )
    save_preferences(path=tmp_path / "preferences.json", preferences=preferences)
    effective = effective_settings(settings=Settings(), config_dir=tmp_path)
    assert effective.embedding_model == "custom:latest"
    assert effective.semantic_search is False


def test_semantic_env_overrides_saved_preferences_and_locks_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SBOBINA_EMBEDDING_MODEL", "pinned:latest")
    monkeypatch.setenv("SBOBINA_SEMANTIC_SEARCH", "false")
    path = tmp_path / "preferences.json"
    save_preferences(path=path, preferences=UserPreferences())
    resolved = resolve_preferences(settings=Settings(), path=path)
    assert resolved.preferences.model_dump()["embedding_model"] == "pinned:latest"
    assert resolved.preferences.model_dump()["semantic_search"] is False
    assert {"embedding_model", "semantic_search"} <= resolved.locked_by_env


def test_semantic_settings_service_persists_runtime_preferences(tmp_path: Path) -> None:
    settings = Settings(config_dir=tmp_path / "config")
    update = settings_service.SemanticIndexUpdate(
        embedding_model="custom:latest", semantic_search=False
    )
    settings_service.update_semantic_index(settings=settings, update=update)
    effective = runtime_settings(settings=settings)
    assert effective.embedding_model == "custom:latest"
    assert effective.semantic_search is False
    view = settings_service.settings_view(settings=settings)
    assert view["preferences"] == UserPreferences(
        embedding_model="custom:latest", semantic_search=False
    ).model_dump(mode="json")


def test_unsafe_settings_view_uses_running_semantic_settings(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        config_dir=tmp_path / "config",
        embedding_model="running:latest",
        semantic_search=False,
    )
    view = settings_service.settings_view(settings=settings)
    preferences = view["preferences"]
    assert isinstance(preferences, dict)
    assert preferences["embedding_model"] == "running:latest"
    assert preferences["semantic_search"] is False


def test_update_transcription_without_audio_consent_preserves_file(
    tmp_path: Path,
) -> None:
    settings = Settings(config_dir=tmp_path)
    path = tmp_path / "preferences.json"
    save_preferences(
        path=path, preferences=UserPreferences(cloud_ack=datetime.now(tz=UTC))
    )
    before = path.read_bytes()
    update = settings_service.TranscriptionUpdate(
        transcription_engine="assemblyai", cloud_ack_audio=False
    )

    with pytest.raises(settings_service.CloudAckRequiredError):
        settings_service.update_transcription(settings=settings, update=update)

    assert path.read_bytes() == before
    assert json.loads(before)["transcription_engine"] == "whisper"


def test_update_transcription_with_audio_consent_saves_timestamp(
    tmp_path: Path,
) -> None:
    settings = Settings(config_dir=tmp_path)
    update = settings_service.TranscriptionUpdate(
        transcription_engine="assemblyai", cloud_ack_audio=True
    )
    started = datetime.now(tz=UTC)

    settings_service.update_transcription(settings=settings, update=update)

    saved = json.loads((tmp_path / "preferences.json").read_text(encoding="utf-8"))
    assert saved["transcription_engine"] == "assemblyai"
    assert (
        started
        <= datetime.fromisoformat(saved["cloud_ack_audio"])
        <= datetime.now(tz=UTC)
    )


def test_update_transcription_existing_audio_consent_is_reused(tmp_path: Path) -> None:
    consent = datetime(year=2025, month=1, day=2, tzinfo=UTC)
    path = tmp_path / "preferences.json"
    save_preferences(path=path, preferences=UserPreferences(cloud_ack_audio=consent))
    update = settings_service.TranscriptionUpdate(
        transcription_engine="assemblyai", cloud_ack_audio=False
    )

    settings_service.update_transcription(
        settings=Settings(config_dir=tmp_path), update=update
    )

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["transcription_engine"] == "assemblyai"
    assert datetime.fromisoformat(saved["cloud_ack_audio"]) == consent


@pytest.mark.parametrize(
    "consent", [None, datetime(year=2025, month=1, day=2, tzinfo=UTC)]
)
def test_update_transcription_whisper_needs_no_consent(
    tmp_path: Path, consent: datetime | None
) -> None:
    path = tmp_path / "preferences.json"
    preferences = UserPreferences(
        transcription_engine="assemblyai", cloud_ack_audio=consent
    )
    save_preferences(path=path, preferences=preferences)
    update = settings_service.TranscriptionUpdate(
        transcription_engine="whisper", cloud_ack_audio=False
    )

    settings_service.update_transcription(
        settings=Settings(config_dir=tmp_path), update=update
    )

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == preferences.model_copy(
        update={"transcription_engine": "whisper"}
    ).model_dump(mode="json")


def test_settings_view_assemblyai_without_key_warns_until_key_saved(
    tmp_path: Path,
) -> None:
    settings = Settings(config_dir=tmp_path)
    save_preferences(
        path=tmp_path / "preferences.json",
        preferences=UserPreferences(
            transcription_engine="assemblyai", cloud_ack_audio=datetime.now(tz=UTC)
        ),
    )

    warnings = settings_service.settings_view(settings=settings)["warnings"]

    assert isinstance(warnings, dict)
    assert warnings["missing_keys"] == ["assemblyai"]
    CredentialStore(config_dir=tmp_path).set_key(
        provider="assemblyai", key="test-audio-key"
    )
    configured = settings_service.settings_view(settings=settings)["warnings"]
    assert isinstance(configured, dict)
    assert configured["missing_keys"] == []

import logging
import stat
from datetime import UTC, datetime
from pathlib import Path

import pydantic
import pytest

from sbobina.settings import LlmChainEntry, Settings
from sbobina.user_preferences import (
    UserPreferences,
    effective_settings,
    preferences_path,
    resolve_preferences,
    save_preferences,
)


def test_resolve_preferences_defaults_when_no_file_and_no_env(tmp_path: Path) -> None:
    resolved = resolve_preferences(
        settings=Settings(), path=tmp_path / "preferences.json"
    )

    assert resolved.preferences.llm_engine == "local"
    assert resolved.preferences.transcription_engine == "whisper"
    assert resolved.locked_by_env == frozenset()


def test_resolve_preferences_reads_the_saved_file(tmp_path: Path) -> None:
    path = tmp_path / "preferences.json"
    save_preferences(
        path=path,
        preferences=UserPreferences(
            llm_engine="api", transcription_engine="assemblyai"
        ),
    )

    resolved = resolve_preferences(settings=Settings(), path=path)

    assert resolved.preferences.llm_engine == "api"
    assert resolved.preferences.transcription_engine == "assemblyai"
    assert resolved.locked_by_env == frozenset()


def test_resolve_preferences_env_wins_over_file_and_reports_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "preferences.json"
    save_preferences(path=path, preferences=UserPreferences(llm_engine="api"))
    monkeypatch.setenv("SBOBINA_LLM_ENGINE", "local")

    resolved = resolve_preferences(settings=Settings(), path=path)

    assert resolved.preferences.llm_engine == "local"
    assert "llm_engine" in resolved.locked_by_env


def test_resolve_preferences_unrelated_fields_are_not_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "preferences.json"
    monkeypatch.setenv("SBOBINA_LLM_ENGINE", "api")

    resolved = resolve_preferences(settings=Settings(), path=path)

    assert resolved.locked_by_env == frozenset({"llm_engine"})
    assert "transcription_engine" not in resolved.locked_by_env


def test_resolve_preferences_on_a_corrupted_file_warns_and_defaults_without_rewriting(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "preferences.json"
    path.write_text("{not json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        resolved = resolve_preferences(settings=Settings(), path=path)

    assert resolved.preferences.llm_engine == "local"
    assert path.read_text(encoding="utf-8") == "{not json"
    assert any("preferen" in record.message.lower() for record in caplog.records)


def test_user_preferences_rejects_a_duplicate_chain_pair() -> None:
    entry = LlmChainEntry(provider="groq", model="llama")
    with pytest.raises(pydantic.ValidationError, match="duplicate"):
        UserPreferences(llm_chain=[entry, entry])


def test_save_preferences_writes_a_file_with_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / "preferences.json"

    save_preferences(path=path, preferences=UserPreferences(llm_engine="api"))

    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_effective_settings_applies_resolved_preferences(tmp_path: Path) -> None:
    config_dir = tmp_path
    save_preferences(
        path=config_dir / "preferences.json",
        preferences=UserPreferences(
            llm_engine="api",
            transcription_engine="assemblyai",
            llm_chain=[LlmChainEntry(provider="groq", model="llama-3.3")],
            cloud_ack=datetime.now(tz=UTC),
            cloud_ack_audio=datetime.now(tz=UTC),
        ),
    )

    resolved = effective_settings(settings=Settings(), config_dir=config_dir)

    assert resolved.llm_engine == "api"
    assert resolved.transcription_engine == "assemblyai"
    assert resolved.llm_chain == [LlmChainEntry(provider="groq", model="llama-3.3")]


def test_effective_settings_without_a_file_matches_defaults(tmp_path: Path) -> None:
    resolved = effective_settings(settings=Settings(), config_dir=tmp_path)

    assert resolved.llm_engine == "local"
    assert resolved.transcription_engine == "whisper"


def test_effective_settings_child_rebuilt_settings_still_read_the_file(
    tmp_path: Path,
) -> None:
    save_preferences(
        path=preferences_path(tmp_path),
        preferences=UserPreferences(
            llm_engine="api",
            llm_chain=[LlmChainEntry(provider="groq", model="llama-x")],
            cloud_ack=datetime.now(tz=UTC),
        ),
    )
    # stage_runner rebuilds Settings from a full dump: every field is "set".
    rebuilt = Settings.model_validate(Settings().model_dump())

    effective = effective_settings(settings=rebuilt, config_dir=tmp_path)

    assert effective.llm_engine == "api"
    assert [entry.model for entry in effective.llm_chain] == ["llama-x"]


def test_effective_settings_without_a_file_keeps_passed_settings(
    tmp_path: Path,
) -> None:
    passed = Settings(llm_engine="api")

    assert effective_settings(settings=passed, config_dir=tmp_path) is passed


def test_effective_settings_cloud_engines_without_consent_stay_local(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    save_preferences(
        path=preferences_path(tmp_path),
        preferences=UserPreferences(
            llm_engine="api",
            llm_chain=[LlmChainEntry(provider="groq", model="llama-x")],
            transcription_engine="assemblyai",
        ),
    )

    with caplog.at_level(logging.WARNING):
        effective = effective_settings(settings=Settings(), config_dir=tmp_path)

    assert effective.llm_engine == "local"
    assert effective.transcription_engine == "whisper"
    assert "consenso" in caplog.text


def test_effective_settings_cloud_engines_with_consent_apply(tmp_path: Path) -> None:
    now = datetime.now(tz=UTC)
    save_preferences(
        path=preferences_path(tmp_path),
        preferences=UserPreferences(
            llm_engine="api",
            llm_chain=[LlmChainEntry(provider="groq", model="llama-x")],
            transcription_engine="assemblyai",
            cloud_ack=now,
            cloud_ack_audio=now,
        ),
    )

    effective = effective_settings(settings=Settings(), config_dir=tmp_path)

    assert effective.llm_engine == "api"
    assert effective.transcription_engine == "assemblyai"


def test_effective_settings_engine_pinned_by_env_needs_no_saved_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SBOBINA_LLM_ENGINE", "api")
    save_preferences(
        path=preferences_path(tmp_path), preferences=UserPreferences(llm_engine="api")
    )

    effective = effective_settings(settings=Settings(), config_dir=tmp_path)

    assert effective.llm_engine == "api"

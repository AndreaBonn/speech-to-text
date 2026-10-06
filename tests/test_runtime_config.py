from pathlib import Path

from sbobina.credential_store import CredentialStore
from sbobina.runtime_config import runtime_keys, runtime_settings
from sbobina.settings import LlmChainEntry, Settings
from sbobina.user_preferences import (
    UserPreferences,
    preferences_path,
    save_preferences,
)

SENTINEL_KEY = "sk-SENTINEL-0123456789abcdef"


def _settings(config_dir: Path) -> Settings:
    return Settings(config_dir=config_dir)


def test_runtime_settings_applies_saved_engine_and_chain(tmp_path: Path) -> None:
    save_preferences(
        path=preferences_path(tmp_path),
        preferences=UserPreferences(
            llm_engine="api",
            llm_chain=[LlmChainEntry(provider="groq", model="llama-x")],
        ),
    )

    effective = runtime_settings(settings=_settings(config_dir=tmp_path))

    assert effective.llm_engine == "api"
    assert [entry.provider for entry in effective.llm_chain] == ["groq"]


def test_runtime_settings_without_saved_preferences_keeps_local(
    tmp_path: Path,
) -> None:
    assert runtime_settings(settings=_settings(config_dir=tmp_path)).llm_engine == (
        "local"
    )


def test_runtime_keys_reads_keys_saved_from_the_ui(tmp_path: Path) -> None:
    CredentialStore(config_dir=tmp_path).set_key(provider="groq", key=SENTINEL_KEY)

    keys = runtime_keys(settings=_settings(config_dir=tmp_path))

    assert keys == {"groq": SENTINEL_KEY}


def test_runtime_keys_unsafe_config_dir_falls_back_to_env_only(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    unsafe = data_dir / "config"
    unsafe.mkdir(parents=True)
    CredentialStore(config_dir=unsafe).set_key(provider="groq", key=SENTINEL_KEY)

    keys = runtime_keys(settings=Settings(config_dir=unsafe, data_dir=data_dir))

    assert keys == {}

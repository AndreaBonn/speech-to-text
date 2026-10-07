from pathlib import Path

import pytest

from sbobina import settings_service
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

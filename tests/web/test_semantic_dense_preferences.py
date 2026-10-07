from pathlib import Path
from unittest.mock import Mock

import pytest
from starlette.requests import Request

from sbobina.ollama_embed import ModelStatus
from sbobina.settings import Settings
from sbobina.settings_service import SemanticIndexUpdate, update_semantic_index
from sbobina.web import api_chat, dense_factory
from sbobina.web.app import create_app


@pytest.fixture
def request_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Request:
    settings = Settings(data_dir=tmp_path / "data", config_dir=tmp_path / "config")
    app = create_app(settings=settings, data_dir=settings.data_dir)
    app.state.chat_client = Mock()
    monkeypatch.setattr(dense_factory, "Client", Mock())
    monkeypatch.setattr(
        dense_factory,
        "model_status",
        Mock(return_value=ModelStatus(digest="test", dimensions=2)),
    )
    return Request(scope={"type": "http", "app": app})


def _save(request: Request, model: str, enabled: bool) -> None:
    update_semantic_index(
        settings=request.app.state.settings,
        update=SemanticIndexUpdate(embedding_model=model, semantic_search=enabled),
    )


def test_chat_dense_services_observe_saved_toggle_without_restart(
    request_context: Request,
) -> None:
    _save(request=request_context, model="saved:latest", enabled=False)
    disabled = api_chat._services(request=request_context).dense
    assert disabled.model == "saved:latest"
    assert disabled.reason == "disabled"
    assert disabled.ranker is None
    _save(request=request_context, model="saved:latest", enabled=True)
    enabled = api_chat._services(request=request_context).dense
    assert enabled.model == "saved:latest"
    assert enabled.reason is None
    assert enabled.ranker is not None


def test_chat_dense_services_replace_cached_ranker_after_saved_model_change(
    request_context: Request,
) -> None:
    _save(request=request_context, model="first:latest", enabled=True)
    first = api_chat._services(request=request_context).dense
    _save(request=request_context, model="second:latest", enabled=True)
    second = api_chat._services(request=request_context).dense
    assert first.model == "first:latest"
    assert second.model == "second:latest"
    assert first.ranker is not None
    assert second.ranker is not None
    assert second.ranker is not first.ranker

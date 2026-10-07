from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sbobina.settings import Settings
from sbobina.web.app import create_app

BASE_URL = "http://127.0.0.1:8765"
SETTINGS_URL = "/api/v1/settings/semantic-index"
PAYLOAD = {"embedding_model": "custom:latest", "semantic_search": False}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    transport = TestClient(app=app, base_url=BASE_URL, headers={"Origin": BASE_URL})
    yield transport
    transport.close()


def test_put_semantic_settings_returns_saved_preferences(client: TestClient) -> None:
    response = client.put(SETTINGS_URL, json=PAYLOAD)
    assert response.status_code == 200
    preferences = response.json()["data"]["preferences"]
    assert preferences["embedding_model"] == "custom:latest"
    assert preferences["semantic_search"] is False
    assert client.get("/api/v1/settings").json()["data"]["preferences"] == preferences


@pytest.mark.parametrize("model", ["", " ", "\t"])
def test_put_semantic_settings_rejects_blank_model(
    client: TestClient, model: str
) -> None:
    response = client.put(SETTINGS_URL, json=PAYLOAD | {"embedding_model": model})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("origin", [None, "http://foreign.invalid"])
def test_put_semantic_settings_requires_own_origin(
    client: TestClient, origin: str | None
) -> None:
    client.headers.pop("Origin")
    headers = {"Origin": origin} if origin else {}
    response = client.put(SETTINGS_URL, json=PAYLOAD, headers=headers)
    assert response.status_code == 403
    client.headers["Origin"] = BASE_URL
    assert client.put(SETTINGS_URL, json=PAYLOAD).status_code == 200


@pytest.mark.parametrize(
    "field,value", [("embedding_model", "pinned"), ("semantic_search", "true")]
)
def test_put_semantic_settings_env_lock_is_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    monkeypatch.setenv(f"SBOBINA_{field.upper()}", value)
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL, headers={"Origin": BASE_URL}) as client:
        response = client.put(SETTINGS_URL, json=PAYLOAD)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "LOCKED_BY_ENV"
        assert field in client.get("/api/v1/settings").json()["data"]["locked_by_env"]

from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sbobina import key_check
from sbobina.settings import Settings
from sbobina.web.app import create_app

BASE_URL = "http://127.0.0.1:8765"
SETTINGS_URL = "/api/v1/settings"
SENTINEL_KEY = "sk-SENTINEL-0123456789abcdef"
API_CHAIN = [{"provider": "groq", "model": "llama-x"}]


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    transport = TestClient(app=app, base_url=BASE_URL, headers={"Origin": BASE_URL})
    yield transport
    transport.close()


def _put_api_engine(client: TestClient, chain: list[dict[str, str]]) -> None:
    response = client.put(
        f"{SETTINGS_URL}/llm",
        json={"llm_engine": "api", "llm_chain": chain, "cloud_ack": True},
    )
    assert response.status_code == 200


def test_read_settings_defaults_to_local_without_warnings(client: TestClient) -> None:
    data = client.get(SETTINGS_URL).json()["data"]

    assert data["preferences"]["llm_engine"] == "local"
    assert data["warnings"] == {"missing_keys": [], "empty_chain": False}
    assert data["keys"]["groq"] == {"configured": False, "last4": None, "source": None}


def test_put_llm_api_without_consent_is_409(client: TestClient) -> None:
    response = client.put(
        f"{SETTINGS_URL}/llm", json={"llm_engine": "api", "llm_chain": API_CHAIN}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CLOUD_ACK_REQUIRED"


def test_put_llm_api_with_consent_warns_about_missing_keys(client: TestClient) -> None:
    chain = [*API_CHAIN, {"provider": "openai", "model": "gpt-x"}]
    _put_api_engine(client=client, chain=chain)
    client.put(f"{SETTINGS_URL}/keys/groq", json={"key": SENTINEL_KEY})

    data = client.get(SETTINGS_URL).json()["data"]

    assert data["preferences"]["llm_engine"] == "api"
    assert data["preferences"]["cloud_ack"] is not None
    assert data["warnings"]["missing_keys"] == ["openai"]


def test_put_llm_back_to_local_keeps_consent_and_clears_warnings(
    client: TestClient,
) -> None:
    _put_api_engine(client=client, chain=API_CHAIN)

    response = client.put(f"{SETTINGS_URL}/llm", json={"llm_engine": "local"})

    data = response.json()["data"]
    assert data["preferences"]["llm_engine"] == "local"
    assert data["warnings"]["missing_keys"] == []


def test_put_llm_field_pinned_by_env_is_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SBOBINA_LLM_ENGINE", "local")

    response = client.put(
        f"{SETTINGS_URL}/llm",
        json={"llm_engine": "api", "llm_chain": API_CHAIN, "cloud_ack": True},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LOCKED_BY_ENV"


def test_put_key_returns_only_the_masked_view(client: TestClient) -> None:
    response = client.put(f"{SETTINGS_URL}/keys/groq", json={"key": SENTINEL_KEY})

    assert response.status_code == 200
    assert response.json()["data"] == {
        "provider": "groq",
        "configured": True,
        "last4": "cdef",
        "source": "file",
    }
    assert SENTINEL_KEY not in response.text


def test_put_key_with_newline_is_422_without_echo(client: TestClient) -> None:
    response = client.put(
        f"{SETTINGS_URL}/keys/groq", json={"key": f"{SENTINEL_KEY}\nX"}
    )

    assert response.status_code == 422
    assert SENTINEL_KEY not in response.text


def test_put_key_unknown_provider_is_404(client: TestClient) -> None:
    response = client.put(f"{SETTINGS_URL}/keys/foo", json={"key": SENTINEL_KEY})

    assert response.status_code == 404


def test_delete_key_removes_it(client: TestClient) -> None:
    client.put(f"{SETTINGS_URL}/keys/groq", json={"key": SENTINEL_KEY})

    response = client.delete(f"{SETTINGS_URL}/keys/groq")

    assert response.status_code == 204
    keys = client.get(SETTINGS_URL).json()["data"]["keys"]
    assert keys["groq"]["configured"] is False


@pytest.mark.parametrize("origin", [None, "http://evil.example"])
def test_settings_mutation_without_own_origin_is_403(
    client: TestClient, origin: str | None
) -> None:
    headers = {"Origin": origin} if origin is not None else {}
    client.headers.pop("Origin")

    response = client.put(
        f"{SETTINGS_URL}/keys/groq", json={"key": SENTINEL_KEY}, headers=headers
    )

    assert response.status_code == 403
    client.headers["Origin"] = BASE_URL
    keys = client.get(SETTINGS_URL).json()["data"]["keys"]
    assert keys["groq"]["configured"] is False


def test_test_key_reports_the_check_result(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str | None] = []

    def fake_check(
        provider: str, api_key: str | None, timeout_s: float
    ) -> key_check.KeyCheckResult:
        seen.append(api_key)
        return "auth"

    monkeypatch.setattr(key_check, "check_key", fake_check)
    client.put(f"{SETTINGS_URL}/keys/groq", json={"key": SENTINEL_KEY})

    response = client.post(f"{SETTINGS_URL}/keys/groq/test")

    assert response.json()["data"] == {"provider": "groq", "result": "auth"}
    assert seen == [SENTINEL_KEY]


def test_no_get_route_ever_returns_a_saved_key(client: TestClient) -> None:
    client.put(f"{SETTINGS_URL}/keys/groq", json={"key": SENTINEL_KEY})
    spec = cast(FastAPI, client.app).openapi()
    paths = [
        path
        for path, operations in spec["paths"].items()
        if "get" in operations and "{" not in path and not path.endswith("/events")
    ]

    bodies = [client.get(path).text for path in paths]

    assert SETTINGS_URL in paths
    assert all(SENTINEL_KEY not in body for body in bodies)


def test_read_settings_without_origin_is_allowed_like_a_browser_get(
    client: TestClient,
) -> None:
    client.headers.pop("Origin")

    response = client.get(SETTINGS_URL)

    assert response.status_code == 200


def test_read_settings_with_a_foreign_origin_is_403(client: TestClient) -> None:
    response = client.get(SETTINGS_URL, headers={"Origin": "http://evil.example"})

    assert response.status_code == 403

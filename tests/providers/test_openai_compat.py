"""OpenAI-compatible adapter: OpenAI, Groq, Gemini. MockTransport only."""

import json
import logging

import httpx
import pytest

from sbobina.correction import InvalidResponseError
from sbobina.llm_corrector import _CorrectionResponse
from sbobina.llm_errors import FailureKind, ProviderUnavailableError
from sbobina.ollama_chat import ChatRequest
from sbobina.providers.openai_compat import (
    PROFILES,
    list_models,
    make_openai_compat_client,
)

SENTINEL_KEY = "sk-SENTINEL-0123456789abcdef"


def _schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
    }


def _request(model: str = "model-x", num_predict: int | None = None) -> ChatRequest:
    return ChatRequest(
        model=model,
        system_prompt="sys",
        user_message="hi",
        schema=_schema(),
        num_predict=num_predict,
    )


def _ok_body(
    content: str = '{"x": "y"}', finish_reason: str = "stop"
) -> dict[str, object]:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def test_make_openai_compat_client_returns_repaired_json_on_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_body(content='```json\n{"x": "y"}\n```'))

    client = make_openai_compat_client(
        profile=PROFILES["openai"],
        api_key=SENTINEL_KEY,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )

    result = client(_request())

    assert json.loads(result) == {"x": "y"}


def test_make_openai_compat_client_sends_key_in_header_never_in_url() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_ok_body())

    client = make_openai_compat_client(
        profile=PROFILES["openai"],
        api_key=SENTINEL_KEY,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )

    client(_request())

    assert captured[0].headers["Authorization"] == f"Bearer {SENTINEL_KEY}"
    assert SENTINEL_KEY not in str(captured[0].url)


def test_make_openai_compat_client_maps_401_to_auth_without_leaking_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        masked = f"{SENTINEL_KEY[:7]}...{SENTINEL_KEY[-4:]}"
        return httpx.Response(
            401, json={"error": {"message": f"Incorrect API key: {masked}"}}
        )

    client = make_openai_compat_client(
        profile=PROFILES["openai"],
        api_key=SENTINEL_KEY,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderUnavailableError) as excinfo:
        client(_request())

    assert excinfo.value.kind == FailureKind.AUTH
    assert SENTINEL_KEY not in str(excinfo.value)
    assert SENTINEL_KEY[-4:] not in str(excinfo.value)


def test_make_openai_compat_client_maps_429_with_retry_after() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "30"}, json={})

    client = make_openai_compat_client(
        profile=PROFILES["groq"],
        api_key=SENTINEL_KEY,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderUnavailableError) as excinfo:
        client(_request())

    assert excinfo.value.kind == FailureKind.RATE_LIMIT
    assert excinfo.value.retry_after_s == 30.0


@pytest.mark.parametrize("status", [503, 529, 413])
def test_make_openai_compat_client_maps_5xx_to_server(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={})

    client = make_openai_compat_client(
        profile=PROFILES["openai"],
        api_key=SENTINEL_KEY,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderUnavailableError) as excinfo:
        client(_request())

    assert excinfo.value.kind == FailureKind.SERVER


def test_make_openai_compat_client_maps_connect_timeout_to_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    client = make_openai_compat_client(
        profile=PROFILES["openai"],
        api_key=SENTINEL_KEY,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderUnavailableError) as excinfo:
        client(_request())

    assert excinfo.value.kind == FailureKind.TIMEOUT


def test_make_openai_compat_client_falls_back_to_json_object_after_one_400() -> None:
    queued = [
        httpx.Response(400, json={"error": "schema rejected"}),
        httpx.Response(200, json=_ok_body()),
    ]
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return queued.pop(0) if queued else httpx.Response(200, json=_ok_body())

    client = make_openai_compat_client(
        profile=PROFILES["groq"],
        api_key=SENTINEL_KEY,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )

    result = client(_request(model="llama"))

    assert json.loads(result) == {"x": "y"}
    assert len(seen) == 2
    first_format = json.loads(seen[0].content)["response_format"]
    assert first_format["type"] == "json_schema"
    second_format = json.loads(seen[1].content)["response_format"]
    assert second_format == {"type": "json_object"}

    client(_request(model="llama"))

    assert len(seen) == 3
    third_format = json.loads(seen[2].content)["response_format"]
    assert third_format == {"type": "json_object"}


def test_make_openai_compat_client_raises_bad_request_when_json_object_also_rejected() -> (
    None
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad"})

    client = make_openai_compat_client(
        profile=PROFILES["openai"],
        api_key=SENTINEL_KEY,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderUnavailableError) as excinfo:
        client(_request())

    assert excinfo.value.kind == FailureKind.BAD_REQUEST


def test_make_openai_compat_client_warns_on_truncated_reply(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=_ok_body(content='{"x": "partial', finish_reason="length")
        )

    client = make_openai_compat_client(
        profile=PROFILES["openai"],
        api_key=SENTINEL_KEY,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )

    with caplog.at_level(logging.WARNING, logger="sbobina"):
        client(_request())

    assert any("troncata" in record.message for record in caplog.records)


def test_make_openai_compat_client_raises_invalid_response_on_empty_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_body(content=""))

    client = make_openai_compat_client(
        profile=PROFILES["openai"],
        api_key=SENTINEL_KEY,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(InvalidResponseError):
        client(_request())


def test_make_openai_compat_client_raises_invalid_response_on_malformed_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json at all")

    client = make_openai_compat_client(
        profile=PROFILES["openai"],
        api_key=SENTINEL_KEY,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(InvalidResponseError):
        client(_request())


@pytest.mark.parametrize(
    ("provider_name", "token_param"),
    [
        ("openai", "max_completion_tokens"),
        ("groq", "max_completion_tokens"),
        ("gemini", "max_tokens"),
    ],
)
def test_make_openai_compat_client_uses_the_profiles_token_param(
    provider_name: str, token_param: str
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_ok_body())

    client = make_openai_compat_client(
        profile=PROFILES[provider_name],
        api_key=SENTINEL_KEY,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )

    client(_request(num_predict=512))

    body = json.loads(captured[0].content)
    assert body[token_param] == 512


def test_make_openai_compat_client_openai_never_sends_temperature() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_ok_body())

    client = make_openai_compat_client(
        profile=PROFILES["openai"],
        api_key=SENTINEL_KEY,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )

    client(_request())

    body = json.loads(captured[0].content)
    assert "temperature" not in body


@pytest.mark.parametrize("provider_name", ["groq", "gemini"])
def test_make_openai_compat_client_sends_temperature_zero_for_groq_and_gemini(
    provider_name: str,
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_ok_body())

    client = make_openai_compat_client(
        profile=PROFILES[provider_name],
        api_key=SENTINEL_KEY,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )

    client(_request())

    body = json.loads(captured[0].content)
    assert body["temperature"] == 0


def test_make_openai_compat_client_sends_portable_schema_for_a_real_response_model() -> (
    None
):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_ok_body())

    client = make_openai_compat_client(
        profile=PROFILES["openai"],
        api_key=SENTINEL_KEY,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )
    request = ChatRequest(
        model="m",
        system_prompt="s",
        user_message="u",
        schema=_CorrectionResponse.model_json_schema(),
    )

    client(request)

    sent_schema = json.loads(captured[0].content)["response_format"]["json_schema"][
        "schema"
    ]
    assert "$defs" not in sent_schema
    assert sent_schema["additionalProperties"] is False


def test_list_models_raises_provider_unavailable_on_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={})

    with pytest.raises(ProviderUnavailableError) as excinfo:
        list_models(
            profile=PROFILES["openai"],
            api_key=SENTINEL_KEY,
            timeout_s=5,
            transport=httpx.MockTransport(handler),
        )

    assert excinfo.value.kind == FailureKind.AUTH


def test_list_models_does_not_raise_on_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    list_models(
        profile=PROFILES["openai"],
        api_key=SENTINEL_KEY,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize(
    ("provider_name", "expected"),
    [("gemini", "minimal"), ("openai", None), ("groq", None)],
)
def test_make_openai_compat_client_limits_reasoning_only_for_gemini(
    provider_name: str, expected: str | None
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_ok_body())

    client = make_openai_compat_client(
        profile=PROFILES[provider_name],
        api_key=SENTINEL_KEY,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )

    client(_request())

    assert json.loads(captured[0].content).get("reasoning_effort") == expected

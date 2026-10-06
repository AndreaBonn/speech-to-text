"""Anthropic Messages adapter: no temperature, max_tokens mandatory."""

import json
import logging

import httpx
import pytest
from sbobina.providers.anthropic import (
    DEFAULT_MAX_TOKENS,
    list_models,
    make_anthropic_client,
)

from sbobina.correction import InvalidResponseError
from sbobina.llm_corrector import _CorrectionResponse
from sbobina.llm_errors import FailureKind, ProviderUnavailableError
from sbobina.ollama_chat import ChatRequest

SENTINEL_KEY = "sk-ant-SENTINEL-0123456789abcdef"


def _schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
    }


def _request(model: str = "claude-x", num_predict: int | None = None) -> ChatRequest:
    return ChatRequest(
        model=model,
        system_prompt="sys",
        user_message="hi",
        schema=_schema(),
        num_predict=num_predict,
    )


def _ok_body(
    text: str = '{"x": "y"}', stop_reason: str = "end_turn"
) -> dict[str, object]:
    return {
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "usage": {"input_tokens": 12, "output_tokens": 7},
    }


def test_make_anthropic_client_returns_repaired_json_on_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_body(text='```json\n{"x": "y"}\n```'))

    client = make_anthropic_client(
        api_key=SENTINEL_KEY, timeout_s=5, transport=httpx.MockTransport(handler)
    )

    result = client(_request())

    assert json.loads(result) == {"x": "y"}


def test_make_anthropic_client_sends_key_in_header_never_in_url() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_ok_body())

    client = make_anthropic_client(
        api_key=SENTINEL_KEY, timeout_s=5, transport=httpx.MockTransport(handler)
    )

    client(_request())

    assert captured[0].headers["x-api-key"] == SENTINEL_KEY
    assert captured[0].headers["anthropic-version"] == "2023-06-01"
    assert SENTINEL_KEY not in str(captured[0].url)


def test_make_anthropic_client_maps_401_to_auth_without_leaking_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid x-api-key"}})

    client = make_anthropic_client(
        api_key=SENTINEL_KEY, timeout_s=5, transport=httpx.MockTransport(handler)
    )

    with pytest.raises(ProviderUnavailableError) as excinfo:
        client(_request())

    assert excinfo.value.kind == FailureKind.AUTH
    assert SENTINEL_KEY not in str(excinfo.value)


def test_make_anthropic_client_maps_429_with_retry_after() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "30"}, json={})

    client = make_anthropic_client(
        api_key=SENTINEL_KEY, timeout_s=5, transport=httpx.MockTransport(handler)
    )

    with pytest.raises(ProviderUnavailableError) as excinfo:
        client(_request())

    assert excinfo.value.kind == FailureKind.RATE_LIMIT
    assert excinfo.value.retry_after_s == 30.0


def test_make_anthropic_client_maps_529_overloaded_to_server() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(529, json={"error": {"type": "overloaded_error"}})

    client = make_anthropic_client(
        api_key=SENTINEL_KEY, timeout_s=5, transport=httpx.MockTransport(handler)
    )

    with pytest.raises(ProviderUnavailableError) as excinfo:
        client(_request())

    assert excinfo.value.kind == FailureKind.SERVER


def test_make_anthropic_client_maps_connect_timeout_to_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    client = make_anthropic_client(
        api_key=SENTINEL_KEY, timeout_s=5, transport=httpx.MockTransport(handler)
    )

    with pytest.raises(ProviderUnavailableError) as excinfo:
        client(_request())

    assert excinfo.value.kind == FailureKind.TIMEOUT


def test_make_anthropic_client_never_sends_temperature() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_ok_body())

    client = make_anthropic_client(
        api_key=SENTINEL_KEY, timeout_s=5, transport=httpx.MockTransport(handler)
    )

    client(_request())

    body = json.loads(captured[0].content)
    assert "temperature" not in body


def test_make_anthropic_client_uses_default_max_tokens_when_num_predict_is_none() -> (
    None
):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_ok_body())

    client = make_anthropic_client(
        api_key=SENTINEL_KEY, timeout_s=5, transport=httpx.MockTransport(handler)
    )

    client(_request(num_predict=None))

    body = json.loads(captured[0].content)
    assert body["max_tokens"] == DEFAULT_MAX_TOKENS


def test_make_anthropic_client_uses_num_predict_as_max_tokens_when_given() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_ok_body())

    client = make_anthropic_client(
        api_key=SENTINEL_KEY, timeout_s=5, transport=httpx.MockTransport(handler)
    )

    client(_request(num_predict=256))

    body = json.loads(captured[0].content)
    assert body["max_tokens"] == 256


def test_make_anthropic_client_warns_on_max_tokens_stop_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=_ok_body(text='{"x": "partial', stop_reason="max_tokens")
        )

    client = make_anthropic_client(
        api_key=SENTINEL_KEY, timeout_s=5, transport=httpx.MockTransport(handler)
    )

    with caplog.at_level(logging.WARNING, logger="sbobina"):
        client(_request())

    assert any("troncata" in record.message for record in caplog.records)


def test_make_anthropic_client_raises_invalid_response_on_empty_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_body(text=""))

    client = make_anthropic_client(
        api_key=SENTINEL_KEY, timeout_s=5, transport=httpx.MockTransport(handler)
    )

    with pytest.raises(InvalidResponseError):
        client(_request())


def test_make_anthropic_client_raises_invalid_response_on_malformed_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json at all")

    client = make_anthropic_client(
        api_key=SENTINEL_KEY, timeout_s=5, transport=httpx.MockTransport(handler)
    )

    with pytest.raises(InvalidResponseError):
        client(_request())


def test_make_anthropic_client_falls_back_without_output_config_after_one_400() -> None:
    queued = [
        httpx.Response(400, json={"error": "schema rejected"}),
        httpx.Response(200, json=_ok_body()),
    ]
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return queued.pop(0) if queued else httpx.Response(200, json=_ok_body())

    client = make_anthropic_client(
        api_key=SENTINEL_KEY, timeout_s=5, transport=httpx.MockTransport(handler)
    )

    result = client(_request(model="opus"))

    assert json.loads(result) == {"x": "y"}
    assert len(seen) == 2
    assert "output_config" in json.loads(seen[0].content)
    assert "output_config" not in json.loads(seen[1].content)

    client(_request(model="opus"))

    assert len(seen) == 3
    assert "output_config" not in json.loads(seen[2].content)


def test_make_anthropic_client_raises_bad_request_when_fallback_also_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad"})

    client = make_anthropic_client(
        api_key=SENTINEL_KEY, timeout_s=5, transport=httpx.MockTransport(handler)
    )

    with pytest.raises(ProviderUnavailableError) as excinfo:
        client(_request())

    assert excinfo.value.kind == FailureKind.BAD_REQUEST


def test_make_anthropic_client_sends_portable_schema_for_a_real_response_model() -> (
    None
):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_ok_body())

    client = make_anthropic_client(
        api_key=SENTINEL_KEY, timeout_s=5, transport=httpx.MockTransport(handler)
    )
    request = ChatRequest(
        model="m",
        system_prompt="s",
        user_message="u",
        schema=_CorrectionResponse.model_json_schema(),
    )

    client(request)

    sent_schema = json.loads(captured[0].content)["output_config"]["format"]["schema"]
    assert "$defs" not in sent_schema
    assert sent_schema["additionalProperties"] is False


def test_list_models_raises_provider_unavailable_on_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={})

    with pytest.raises(ProviderUnavailableError) as excinfo:
        list_models(
            api_key=SENTINEL_KEY, timeout_s=5, transport=httpx.MockTransport(handler)
        )

    assert excinfo.value.kind == FailureKind.AUTH


def test_list_models_does_not_raise_on_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    list_models(
        api_key=SENTINEL_KEY, timeout_s=5, transport=httpx.MockTransport(handler)
    )

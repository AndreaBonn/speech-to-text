import json
import logging

import httpx
import ollama
import pytest
from pydantic import SecretStr

from sbobina import llm_factory
from sbobina.correction import InvalidResponseError
from sbobina.llm_chain import ChainLink, FallbackChain, ServedByRecorder
from sbobina.llm_errors import (
    ChainExhaustedError,
    FailureKind,
    ProviderUnavailableError,
)
from sbobina.ollama_chat import ChatRequest
from sbobina.providers.openai_compat import PROFILES, make_openai_compat_client
from sbobina.settings import LlmChainEntry, Settings

SENTINEL_KEY = "sk-SENTINEL-abc123"


def test_keys_from_settings_only_returns_configured_providers() -> None:
    settings = Settings(groq_api_key=SecretStr(SENTINEL_KEY), anthropic_api_key=None)

    keys = llm_factory.keys_from_settings(settings)

    assert keys == {"groq": SENTINEL_KEY}


class _AnsweringClient:
    content: str | None = '{"ok": true}'

    def __init__(self, host: str) -> None:
        pass

    def chat(self, **kwargs: object) -> ollama.ChatResponse:
        return ollama.ChatResponse(
            message=ollama.Message(role="assistant", content=self.content)
        )


def test_build_chat_client_local_calls_ensure_model_once_and_builds_no_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_ensure_model(model: str, host: str) -> bool:
        calls.append((model, host))
        return False

    monkeypatch.setattr("sbobina.llm_corrector.ensure_model", fake_ensure_model)
    monkeypatch.setattr(ollama, "Client", _AnsweringClient)
    settings = Settings(llm_engine="local", ollama_model="qwen3.5:9b")

    chat = llm_factory.build_chat_client(settings=settings, keys={})
    request = ChatRequest(
        model="qwen3.5:9b", system_prompt="s", user_message="u", schema={}
    )

    assert chat(request) == '{"ok": true}'
    assert calls == [("qwen3.5:9b", settings.ollama_host)]
    assert not isinstance(chat, FallbackChain)


def test_build_chat_client_local_records_served_by_when_given_a_recorder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sbobina.llm_corrector.ensure_model", lambda model, host: False)
    monkeypatch.setattr(ollama, "Client", _AnsweringClient)
    settings = Settings(llm_engine="local", ollama_model="qwen3.5:9b")
    recorder = ServedByRecorder()

    chat = llm_factory.build_chat_client(settings=settings, keys={}, recorder=recorder)
    request = ChatRequest(
        model="qwen3.5:9b", system_prompt="s", user_message="u", schema={}
    )
    chat(request)

    assert recorder.snapshot() == {"ollama/qwen3.5:9b": 1}


def test_build_chat_client_api_builds_links_in_order_without_network() -> None:
    settings = Settings(
        llm_engine="api",
        llm_chain=[
            LlmChainEntry(provider="groq", model="llama-x"),
            LlmChainEntry(provider="openai", model="gpt-x"),
        ],
        llm_ollama_fallback=True,
        ollama_model="qwen3.5:9b",
    )

    chat = llm_factory.build_chat_client(settings=settings, keys={"groq": SENTINEL_KEY})

    assert isinstance(chat, FallbackChain)
    assert [link.provider for link in chat.links] == ["groq", "openai", "ollama"]


def test_build_chat_client_api_missing_key_link_raises_missing_key_on_first_call() -> (
    None
):
    settings = Settings(
        llm_engine="api",
        llm_chain=[LlmChainEntry(provider="openai", model="gpt-x")],
        llm_ollama_fallback=False,
    )

    chat = llm_factory.build_chat_client(settings=settings, keys={})
    request = ChatRequest(model="gpt-x", system_prompt="s", user_message="u", schema={})

    assert isinstance(chat, FallbackChain)
    with pytest.raises(ProviderUnavailableError) as excinfo:
        chat.links[0].client(request)
    assert excinfo.value.kind == FailureKind.MISSING_KEY


def test_build_chat_client_api_chain_falls_back_and_records_served_by() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "groq" in str(request.url):
            return httpx.Response(429, headers={"Retry-After": "30"})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}
                ],
                "usage": {},
            },
        )

    settings = Settings(
        llm_engine="api",
        llm_chain=[
            LlmChainEntry(provider="groq", model="llama-x"),
            LlmChainEntry(provider="openai", model="gpt-x"),
        ],
        llm_ollama_fallback=False,
    )
    recorder = ServedByRecorder()
    mocked_links = [
        ChainLink(
            provider=entry.provider,
            model=entry.model,
            client=make_openai_compat_client(
                profile=PROFILES[entry.provider],
                api_key=SENTINEL_KEY,
                timeout_s=5,
                transport=httpx.MockTransport(handler),
            ),
        )
        for entry in settings.llm_chain
    ]
    chain = FallbackChain(links=mocked_links, recorder=recorder)
    request = ChatRequest(model="x", system_prompt="s", user_message="u", schema={})

    assert chain(request) == '{"ok": true}'
    assert recorder.snapshot() == {"openai/gpt-x": 1}


def test_effective_model_label_local_is_plain_model() -> None:
    settings = Settings(llm_engine="local", ollama_model="qwen3.5:9b")

    assert llm_factory.effective_model_label(settings) == "qwen3.5:9b"


def test_effective_model_label_api_describes_the_chain() -> None:
    settings = Settings(
        llm_engine="api",
        llm_chain=[LlmChainEntry(provider="groq", model="llama-x")],
        llm_ollama_fallback=True,
        ollama_model="qwen3.5:9b",
    )

    assert (
        llm_factory.effective_model_label(settings)
        == "api: groq/llama-x > ollama/qwen3.5:9b"
    )


def test_ensure_ready_calls_ensure_model_only_for_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "sbobina.llm_corrector.ensure_model",
        lambda model, host: calls.append(model),
    )

    llm_factory.ensure_ready(Settings(llm_engine="api"))
    assert calls == []

    llm_factory.ensure_ready(Settings(llm_engine="local", ollama_model="m"))
    assert calls == ["m"]


def test_effective_model_label_api_optional_fallback_is_last() -> None:
    settings = Settings(
        llm_engine="api",
        llm_ollama_fallback=False,
        ollama_model="local-model",
        llm_chain=[LlmChainEntry(provider="anthropic", model="cloud-model")],
    )

    without_fallback = llm_factory.effective_model_label(settings=settings)
    settings.llm_ollama_fallback = True
    with_fallback = llm_factory.effective_model_label(settings=settings)

    assert without_fallback == "api: anthropic/cloud-model"
    assert with_fallback == "api: anthropic/cloud-model > ollama/local-model"


@pytest.fixture
def anthropic_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def handle(
        transport: httpx.HTTPTransport, request: httpx.Request
    ) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status_code=200,
            json={
                "content": [{"type": "text", "text": '{"ok": true}'}],
                "stop_reason": "end_turn",
            },
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    return requests


def test_build_chat_client_anthropic_sends_messages_request(
    anthropic_requests: list[httpx.Request],
) -> None:
    settings = Settings(
        llm_engine="api",
        llm_ollama_fallback=False,
        llm_chain=[LlmChainEntry(provider="anthropic", model="claude-test")],
    )
    chat = llm_factory.build_chat_client(
        settings=settings, keys={"anthropic": SENTINEL_KEY}
    )
    request = ChatRequest(
        model="placeholder", system_prompt="system", user_message="hello", schema={}
    )

    reply = chat(request)

    assert reply == '{"ok": true}'
    assert [(r.method, str(r.url)) for r in anthropic_requests] == [
        ("POST", "https://api.anthropic.com/v1/messages")
    ]
    assert anthropic_requests[0].headers["x-api-key"] == SENTINEL_KEY
    assert json.loads(anthropic_requests[0].content)["model"] == "claude-test"
    assert json.loads(anthropic_requests[0].content)["messages"] == [
        {"role": "user", "content": "hello"}
    ]


def test_fallback_chain_invalid_threshold_warns_once_without_stale_cause(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failure = ProviderUnavailableError(
        kind=FailureKind.NETWORK, provider="network/m", retry_after_s=None
    )

    def invalid(request: ChatRequest) -> str:
        if request.model == "network":
            raise failure
        raise InvalidResponseError("invalid JSON")

    models = ("network", "m")
    links = [ChainLink(provider="p", model=m, client=invalid) for m in models]
    chain = FallbackChain(links=links)
    request = ChatRequest(model="m", system_prompt="s", user_message="u", schema={})
    with caplog.at_level(level=logging.WARNING, logger="sbobina"):
        for _ in range(2):
            with pytest.raises(InvalidResponseError):
                chain(request=request)
        assert caplog.messages == []
        with pytest.raises(InvalidResponseError):
            chain(request=request)
        for _ in range(2):
            with pytest.raises(ChainExhaustedError) as raised:
                chain(request=request)
            assert raised.value.causes == (failure,)
    assert [(r.levelno, r.getMessage()) for r in caplog.records] == [
        (logging.WARNING, "p/m escluso: troppe risposte non valide di fila")
    ]

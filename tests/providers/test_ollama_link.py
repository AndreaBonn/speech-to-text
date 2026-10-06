from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import httpx
import ollama
import pytest

from sbobina.correction import InvalidResponseError
from sbobina.llm_errors import FailureKind, ProviderUnavailableError
from sbobina.ollama_chat import ChatRequest
from sbobina.providers.ollama_link import make_ollama_link_client
from sbobina.web.gpu_lock import GpuBusyError


class FakeOllamaClient:
    """A fake good enough to drive `make_ollama_link_client` without a network."""

    def __init__(
        self,
        *,
        show_error: Exception | None = None,
        chat_content: str | None = '{"ok": true}',
        chat_error: Exception | None = None,
    ) -> None:
        self.show_error = show_error
        self.chat_content = chat_content
        self.chat_error = chat_error
        self.show_calls = 0
        self.pull_calls = 0

    def show(self, model: str) -> None:
        self.show_calls += 1
        if self.show_error is not None:
            raise self.show_error

    def pull(self, model: str) -> None:  # pragma: no cover - must never run
        self.pull_calls += 1

    def chat(self, **kwargs: object) -> ollama.ChatResponse:
        if self.chat_error is not None:
            raise self.chat_error
        return ollama.ChatResponse(
            message=ollama.Message(role="assistant", content=self.chat_content)
        )


def _request(model: str = "qwen3.5:9b") -> ChatRequest:
    return ChatRequest(
        model=model,
        system_prompt="system",
        user_message="user",
        schema={"type": "object"},
    )


def test_missing_model_raises_model_missing_without_pulling() -> None:
    fake = FakeOllamaClient(show_error=ollama.ResponseError("missing", status_code=404))
    chat = make_ollama_link_client(
        model_host="http://localhost:11434",
        timeout_s=None,
        client=cast(ollama.Client, fake),
    )

    with pytest.raises(ProviderUnavailableError) as raised:
        chat(_request())

    assert raised.value.kind == FailureKind.MODEL_MISSING
    assert fake.pull_calls == 0


def test_model_presence_is_checked_only_once_across_requests() -> None:
    fake = FakeOllamaClient()
    chat = make_ollama_link_client(
        model_host="http://localhost:11434",
        timeout_s=None,
        client=cast(ollama.Client, fake),
    )

    for _ in range(3):
        chat(_request())

    assert fake.show_calls == 1


def test_guard_busy_raises_provider_unavailable_preserving_the_cause() -> None:
    fake = FakeOllamaClient()
    busy = GpuBusyError(stage="TRANSCRIBING", estimate_s=None)

    @contextmanager
    def guard() -> Iterator[None]:
        raise busy
        yield  # pragma: no cover - unreachable, satisfies generator syntax

    chat = make_ollama_link_client(
        model_host="http://localhost:11434",
        timeout_s=None,
        guard=guard,
        client=cast(ollama.Client, fake),
    )

    with pytest.raises(ProviderUnavailableError) as raised:
        chat(_request())

    assert raised.value.kind == FailureKind.BUSY
    assert raised.value.__cause__ is busy


def test_without_a_guard_the_chat_runs_directly() -> None:
    fake = FakeOllamaClient()
    chat = make_ollama_link_client(
        model_host="http://localhost:11434",
        timeout_s=None,
        client=cast(ollama.Client, fake),
    )

    assert chat(_request()) == '{"ok": true}'


def test_connection_refused_maps_to_network() -> None:
    fake = FakeOllamaClient(chat_error=ConnectionError("refused"))
    chat = make_ollama_link_client(
        model_host="http://localhost:11434",
        timeout_s=None,
        client=cast(ollama.Client, fake),
    )

    with pytest.raises(ProviderUnavailableError) as raised:
        chat(_request())

    assert raised.value.kind == FailureKind.NETWORK


def test_timeout_maps_to_timeout_kind() -> None:
    fake = FakeOllamaClient(chat_error=httpx.ReadTimeout("timed out"))
    chat = make_ollama_link_client(
        model_host="http://localhost:11434",
        timeout_s=None,
        client=cast(ollama.Client, fake),
    )

    with pytest.raises(ProviderUnavailableError) as raised:
        chat(_request())

    assert raised.value.kind == FailureKind.TIMEOUT


def test_invalid_response_propagates_unchanged() -> None:
    fake = FakeOllamaClient(chat_error=ValueError("truncated response"))
    chat = make_ollama_link_client(
        model_host="http://localhost:11434",
        timeout_s=None,
        client=cast(ollama.Client, fake),
    )

    with pytest.raises(InvalidResponseError):
        chat(_request())


def test_valid_response_returns_repaired_json() -> None:
    fake = FakeOllamaClient(chat_content='{"a": [{"b": 1}]')
    chat = make_ollama_link_client(
        model_host="http://localhost:11434",
        timeout_s=None,
        client=cast(ollama.Client, fake),
    )

    assert chat(_request()) == '{"a": [{"b": 1}]}'


def test_model_missing_status_overrides_a_later_server_error_check() -> None:
    # The presence check only runs once per model; a transient show() error
    # on a later request for the SAME model must not re-trigger it.
    fake = FakeOllamaClient()
    chat = make_ollama_link_client(
        model_host="http://localhost:11434",
        timeout_s=None,
        client=cast(ollama.Client, fake),
    )
    chat(_request())

    fake.show_error = ollama.ResponseError("down", status_code=500)
    chat(_request())  # must not raise: show() is not called again

    assert fake.show_calls == 1


def test_show_server_error_on_first_check_maps_to_server() -> None:
    fake = FakeOllamaClient(show_error=ollama.ResponseError("down", status_code=500))
    chat = make_ollama_link_client(
        model_host="http://localhost:11434",
        timeout_s=None,
        client=cast(ollama.Client, fake),
    )

    with pytest.raises(ProviderUnavailableError) as raised:
        chat(_request())

    assert raised.value.kind == FailureKind.SERVER


def test_show_connection_error_maps_to_network() -> None:
    fake = FakeOllamaClient(show_error=ConnectionError("refused"))
    chat = make_ollama_link_client(
        model_host="http://localhost:11434",
        timeout_s=None,
        client=cast(ollama.Client, fake),
    )

    with pytest.raises(ProviderUnavailableError) as raised:
        chat(_request())

    assert raised.value.kind == FailureKind.NETWORK

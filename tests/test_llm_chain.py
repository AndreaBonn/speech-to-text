import threading
from collections.abc import Callable

import pytest

from sbobina.correction import InvalidResponseError
from sbobina.llm_chain import ChainLink, FallbackChain, ServedByRecorder
from sbobina.llm_errors import (
    ChainExhaustedError,
    FailureKind,
    ProviderUnavailableError,
)
from sbobina.ollama_chat import ChatRequest

SENTINEL = "sk-SENTINEL-do-not-leak"


def make_request(user_message: str = "testo") -> ChatRequest:
    return ChatRequest(
        model="placeholder",
        system_prompt="sistema",
        user_message=user_message,
        schema={"type": "object"},
    )


def failing_client(
    kind: FailureKind, retry_after_s: float | None = None
) -> Callable[[ChatRequest], str]:
    def client(request: ChatRequest) -> str:
        raise ProviderUnavailableError(
            kind=kind, provider="x/y", retry_after_s=retry_after_s
        )

    return client


def succeeding_client(reply: str) -> Callable[[ChatRequest], str]:
    def client(request: ChatRequest) -> str:
        return reply

    return client


def invalid_client() -> Callable[[ChatRequest], str]:
    def client(request: ChatRequest) -> str:
        raise InvalidResponseError("fuori schema")

    return client


def test_fallback_chain_uses_the_first_eligible_link_that_succeeds() -> None:
    chain = FallbackChain(
        links=[
            ChainLink(
                provider="p1",
                model="m",
                client=failing_client(FailureKind.RATE_LIMIT),
            ),
            ChainLink(provider="p2", model="m", client=succeeding_client("{}")),
        ]
    )

    result = chain(make_request())

    assert result == "{}"
    assert chain.recorder.snapshot() == {"p2/m": 1}


def test_fallback_chain_raises_chain_exhausted_with_every_cause_and_no_key() -> None:
    chain = FallbackChain(
        links=[
            ChainLink(
                provider="p1", model="m", client=failing_client(FailureKind.AUTH)
            ),
            ChainLink(
                provider="p2",
                model="m",
                client=failing_client(FailureKind.RATE_LIMIT),
            ),
            ChainLink(
                provider="p3", model="m", client=failing_client(FailureKind.SERVER)
            ),
        ]
    )

    with pytest.raises(ChainExhaustedError) as exc_info:
        chain(make_request())

    error = exc_info.value
    assert len(error.causes) == 3
    assert SENTINEL not in str(error)


def test_fallback_chain_invalid_response_propagates_without_trying_the_next_link() -> (
    None
):
    calls: list[str] = []

    def second(request: ChatRequest) -> str:
        calls.append(request.user_message)
        return "{}"

    chain = FallbackChain(
        links=[
            ChainLink(provider="p1", model="m", client=invalid_client()),
            ChainLink(provider="p2", model="m", client=second),
        ]
    )

    with pytest.raises(InvalidResponseError):
        chain(make_request())

    assert calls == []


def test_fallback_chain_passes_the_link_model_to_the_client() -> None:
    received: list[str] = []

    def client(request: ChatRequest) -> str:
        received.append(request.model)
        return "{}"

    chain = FallbackChain(
        links=[ChainLink(provider="p1", model="the-model", client=client)]
    )

    chain(make_request())

    assert received == ["the-model"]


def test_fallback_chain_splits_six_chunks_across_two_links_without_repeats() -> None:
    served_chunks: dict[str, list[str]] = {"p1": [], "p2": []}

    def first(request: ChatRequest) -> str:
        if len(served_chunks["p1"]) >= 3:
            raise ProviderUnavailableError(
                kind=FailureKind.RATE_LIMIT, provider="p1/m", retry_after_s=9999.0
            )
        served_chunks["p1"].append(request.user_message)
        return f"ok:{request.user_message}"

    def second(request: ChatRequest) -> str:
        served_chunks["p2"].append(request.user_message)
        return f"ok:{request.user_message}"

    chain = FallbackChain(
        links=[
            ChainLink(provider="p1", model="m", client=first),
            ChainLink(provider="p2", model="m", client=second),
        ]
    )

    results = [chain(make_request(user_message=f"chunk{i}")) for i in range(6)]

    assert results == [f"ok:chunk{i}" for i in range(6)]
    assert served_chunks["p1"] == ["chunk0", "chunk1", "chunk2"]
    assert served_chunks["p2"] == ["chunk3", "chunk4", "chunk5"]
    assert chain.recorder.snapshot() == {"p1/m": 3, "p2/m": 3}


def test_fallback_chain_disabled_link_is_skipped_on_every_later_request() -> None:
    call_count = {"n": 0}

    def flaky(request: ChatRequest) -> str:
        call_count["n"] += 1
        raise ProviderUnavailableError(
            kind=FailureKind.AUTH, provider="p1/m", retry_after_s=None
        )

    def fallback(request: ChatRequest) -> str:
        return "{}"

    chain = FallbackChain(
        links=[
            ChainLink(provider="p1", model="m", client=flaky),
            ChainLink(provider="p2", model="m", client=fallback),
        ]
    )

    for _ in range(50):
        chain(make_request())

    assert call_count["n"] == 1


def test_fallback_chain_is_thread_safe_under_concurrent_calls() -> None:
    chain = FallbackChain(
        links=[
            ChainLink(
                provider="p1",
                model="m",
                client=failing_client(FailureKind.RATE_LIMIT, retry_after_s=9999.0),
            ),
            ChainLink(provider="p2", model="m", client=succeeding_client("{}")),
        ]
    )
    results: list[str] = []
    errors: list[Exception] = []
    results_lock = threading.Lock()

    def worker() -> None:
        for _ in range(20):
            try:
                reply = chain(make_request())
            except Exception as exc:  # noqa: BLE001 - captured to assert in the test
                with results_lock:
                    errors.append(exc)
                continue
            with results_lock:
                results.append(reply)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(results) == 40
    assert all(reply == "{}" for reply in results)


def test_served_by_recorder_counts_by_provider_and_model_label() -> None:
    recorder = ServedByRecorder()

    recorder.add("groq/llama")
    recorder.add("groq/llama")
    recorder.add("ollama/qwen3.5:9b")

    assert recorder.snapshot() == {"groq/llama": 2, "ollama/qwen3.5:9b": 1}

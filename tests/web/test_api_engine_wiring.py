from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import Request

from sbobina.correction import CorrectionResult, CorrectorUnavailableError
from sbobina.llm_chain import FallbackChain
from sbobina.llm_errors import (
    ChainExhaustedError,
    FailureKind,
    ProviderUnavailableError,
)
from sbobina.models import Transcript
from sbobina.pipeline import CorrectionOutcome
from sbobina.settings import LlmChainEntry, Settings
from sbobina.web.api_chat import _chat_client
from sbobina.web.chat_turn import _ollama_error
from sbobina.web.gpu_lock import GpuArbiter, GpuBusyError
from sbobina.web.stage_runner import _check_outcome

SENTINEL_KEY = "sk-SENTINEL-0123456789abcdef"


def _cause(provider: str, kind: FailureKind) -> ProviderUnavailableError:
    return ProviderUnavailableError(kind=kind, provider=provider, retry_after_s=None)


def test_ollama_error_exhausted_chain_returns_503_with_provider_names() -> None:
    leaking = _cause(provider="groq/llama-x", kind=FailureKind.RATE_LIMIT)
    leaking.__cause__ = ConnectionError(f"Authorization: Bearer {SENTINEL_KEY}")
    error = ChainExhaustedError(
        causes=(leaking, _cause(provider="ollama/qwen", kind=FailureKind.NETWORK))
    )
    error.__cause__ = leaking

    app_error = _ollama_error(error=error, arbiter=GpuArbiter())

    assert app_error.code == "LLM_UNAVAILABLE"
    assert "groq/llama-x" in app_error.message
    assert "ollama/qwen" in app_error.message
    assert SENTINEL_KEY in str(error.causes[0].__cause__)
    assert SENTINEL_KEY not in app_error.message


def test_ollama_error_all_links_busy_during_lease_returns_gpu_busy() -> None:
    arbiter = GpuArbiter()
    error = ChainExhaustedError(
        causes=(_cause(provider="ollama/qwen", kind=FailureKind.BUSY),)
    )

    with arbiter.transcription_lease(stage="TRANSCRIBING"):
        app_error = _ollama_error(error=error, arbiter=arbiter)

    assert isinstance(app_error, GpuBusyError)
    assert app_error.code == "GPU_BUSY"


def test_ollama_error_local_engine_keeps_ollama_unavailable() -> None:
    app_error = _ollama_error(
        error=CorrectorUnavailableError("ConnectError: refused"), arbiter=GpuArbiter()
    )

    assert app_error.code == "OLLAMA_UNAVAILABLE"


def _request(settings: Settings) -> Request:
    state = SimpleNamespace(
        settings=settings, chat_client=None, gpu_arbiter=GpuArbiter()
    )
    return cast(Request, SimpleNamespace(app=SimpleNamespace(state=state)))


def _api_settings(model: str) -> Settings:
    return Settings(
        llm_engine="api",
        llm_chain=[LlmChainEntry(provider="groq", model=model)],
        llm_ollama_fallback=False,
    )


def test_chat_client_api_engine_is_cached_until_settings_change() -> None:
    request = _request(settings=_api_settings(model="llama-a"))

    first = _chat_client(request=request)
    same = _chat_client(request=request)
    cast(Any, request.app.state).settings = _api_settings(model="llama-b")
    rebuilt = _chat_client(request=request)

    assert same is first
    assert rebuilt is not first
    assert isinstance(rebuilt, FallbackChain)
    assert [link.model for link in rebuilt.links] == ["llama-b"]


def _interrupted(error: CorrectorUnavailableError) -> CorrectionOutcome:
    transcript = Transcript(
        source="a.m4a", model="m", language="it", duration=1.0, segments=()
    )
    result = CorrectionResult(
        transcript=transcript,
        applied=[],
        rejected=[],
        interrupted_at=12.0,
        interrupted_error=error,
    )
    return CorrectionOutcome(result=result, corrected_json=cast(Path | None, None))


def test_check_outcome_exhausted_chain_reports_its_causes() -> None:
    error = ChainExhaustedError(
        causes=(_cause(provider="groq/llama-x", kind=FailureKind.AUTH),)
    )

    with pytest.raises(CorrectorUnavailableError) as raised:
        _check_outcome(outcome=_interrupted(error=error))

    message = str(raised.value)
    assert "groq/llama-x" in message
    assert "Ollama irraggiungibile" not in message


def test_check_outcome_local_engine_keeps_historic_message() -> None:
    error = CorrectorUnavailableError("ConnectError: refused")

    with pytest.raises(CorrectorUnavailableError, match="Ollama irraggiungibile$"):
        _check_outcome(outcome=_interrupted(error=error))


def test_chat_client_is_rebuilt_when_a_key_is_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SBOBINA_GROQ_API_KEY", "gsk-old-0123456789abcdef")
    request = _request(settings=Settings(**_api_kwargs()))
    first = _chat_client(request=request)

    monkeypatch.setenv("SBOBINA_GROQ_API_KEY", "gsk-new-0123456789abcdef")
    cast(Any, request.app.state).settings = Settings(**_api_kwargs())
    rebuilt = _chat_client(request=request)

    assert rebuilt is not first


def _api_kwargs() -> dict[str, Any]:
    return {
        "llm_engine": "api",
        "llm_chain": [LlmChainEntry(provider="groq", model="llama-a")],
        "llm_ollama_fallback": False,
    }

"""Ollama as the last link of the LLM fallback chain (T021).

Reuses `chat_json`'s reply repair and its mapping of transport failures to
`CorrectorUnavailableError`; the only link-specific behaviour is the
model-presence check (unlike the local engine's `ensure_model`, this link
never pulls a missing model) and the optional GPU guard shared with the
chat/transcription arbiter. The guard reaches into `sbobina.web.gpu_lock`
because arbitration only exists in the web process: the CLI and
`stage_runner` pass `guard=None` and run unguarded.
"""

import threading
from collections.abc import Callable
from contextlib import AbstractContextManager

import httpx
from ollama import Client, ResponseError

from sbobina.chat_pipeline import ChatClient
from sbobina.correction import CorrectorUnavailableError
from sbobina.llm_errors import (
    FailureKind,
    ProviderUnavailableError,
    classify_http_failure,
    classify_transport_error,
)
from sbobina.ollama_chat import ChatRequest, chat_json
from sbobina.web.gpu_lock import GpuBusyError

_PROVIDER = "ollama"
_HTTP_NOT_FOUND = 404

Guard = Callable[[], AbstractContextManager[None]]


def make_ollama_link_client(
    model_host: str,
    timeout_s: float | None,
    guard: Guard | None = None,
    client: Client | None = None,
) -> ChatClient:
    """Build the `ChatClient` for the Ollama link of the fallback chain.

    Parameters
    ----------
    model_host : str
        Ollama server URL, used only when `client` is omitted.
    timeout_s : float | None
        Request timeout passed to the built-in `ollama.Client`.
    guard : Guard | None
        Context manager factory the chat call runs inside, e.g.
        `GpuArbiter.chat_turn`. `None` runs unguarded.
    client : ollama.Client | None
        Injected client, for tests; built from `model_host`/`timeout_s`
        otherwise.
    """
    ollama_client = (
        client if client is not None else Client(host=model_host, timeout=timeout_s)
    )
    checked_models: set[str] = set()
    lock = threading.Lock()

    def chat(request: ChatRequest) -> str:
        _ensure_model_checked(
            client=ollama_client, model=request.model, checked=checked_models, lock=lock
        )
        return _run_guarded(client=ollama_client, request=request, guard=guard)

    return chat


def _run_guarded(client: Client, request: ChatRequest, guard: Guard | None) -> str:
    if guard is None:
        return _chat(client=client, request=request)
    try:
        with guard():
            return _chat(client=client, request=request)
    except GpuBusyError as err:
        raise ProviderUnavailableError(
            kind=FailureKind.BUSY, provider=_PROVIDER, retry_after_s=None
        ) from err


def _chat(client: Client, request: ChatRequest) -> str:
    try:
        return chat_json(client=client, request=request)
    except CorrectorUnavailableError as err:
        cause = err.__cause__
        kind = (
            FailureKind.TIMEOUT
            if isinstance(cause, httpx.TimeoutException)
            else FailureKind.NETWORK
        )
        raise ProviderUnavailableError(
            kind=kind, provider=_PROVIDER, retry_after_s=None
        ) from err


def _ensure_model_checked(
    client: Client, model: str, checked: set[str], lock: threading.Lock
) -> None:
    with lock:
        if model in checked:
            return
        _check_model_presence(client=client, model=model)
        checked.add(model)


def _check_model_presence(client: Client, model: str) -> None:
    try:
        client.show(model)
    except ResponseError as err:
        kind = _classify_show_response_error(err)
        raise ProviderUnavailableError(
            kind=kind, provider=_PROVIDER, retry_after_s=None
        ) from err
    except (ConnectionError, httpx.TransportError) as err:
        raise ProviderUnavailableError(
            kind=classify_transport_error(err), provider=_PROVIDER, retry_after_s=None
        ) from err


def _classify_show_response_error(err: ResponseError) -> FailureKind:
    if err.status_code == _HTTP_NOT_FOUND:
        return FailureKind.MODEL_MISSING
    kind, _retry_after_s = classify_http_failure(status=err.status_code, headers={})
    return kind

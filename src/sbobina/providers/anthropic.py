"""Anthropic Messages API adapter (A1/A2, V2 in adr.md § Verifiche eseguite).

Anthropic never accepts `temperature` on the reasoning models this project
targets (400), so unlike the OpenAI-compatible profiles this adapter sends
none, ever. `max_tokens` is mandatory on every request: `num_predict` maps
to it, with `DEFAULT_MAX_TOKENS` as the fallback the plan requires (C1).
Structured output lives in `output_config.format` (confirmed on the docs);
a model that rejects it answers 400, handled with the same one-shot
fallback as `openai_compat.py` (R2), minus the schema this time.
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from sbobina.chat_pipeline import ChatClient
from sbobina.correction import InvalidResponseError
from sbobina.llm_errors import (
    ProviderUnavailableError,
    classify_http_failure,
    classify_transport_error,
)
from sbobina.llm_repair import repair_json_reply
from sbobina.ollama_chat import ChatRequest
from sbobina.providers.schema_compat import portable_schema

logger = logging.getLogger("sbobina")

BASE_URL = "https://api.anthropic.com"
_MESSAGES_PATH = "/v1/messages"
_MODELS_PATH = "/v1/models"
_ANTHROPIC_VERSION = "2023-06-01"
# Anthropic requires max_tokens on every request; this is the ceiling used
# when the caller passes no num_predict (C1 of plan.md).
DEFAULT_MAX_TOKENS = 4096
_BAD_REQUEST_STATUS = 400
_TRUNCATED_STOP_REASON = "max_tokens"
_PROVIDER_LABEL = "anthropic"


class _SchemaFallbackState:
    """Models observed to reject `output_config`, learned once per client."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._unsupported: set[str] = set()

    def is_unsupported(self, model: str) -> bool:
        with self._lock:
            return model in self._unsupported

    def mark_unsupported(self, model: str) -> None:
        with self._lock:
            self._unsupported.add(model)


@dataclass(frozen=True, kw_only=True)
class _ClientContext:
    client: httpx.Client
    state: _SchemaFallbackState
    headers: dict[str, str]


def _headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": _ANTHROPIC_VERSION,
        "content-type": "application/json",
    }


def _build_body(request: ChatRequest, use_schema: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": request.model,
        "max_tokens": request.num_predict or DEFAULT_MAX_TOKENS,
        "system": request.system_prompt,
        "messages": [{"role": "user", "content": request.user_message}],
    }
    if use_schema:
        body["output_config"] = {
            "format": {
                "type": "json_schema",
                "schema": portable_schema(schema=request.schema),
            }
        }
    return body


def _post(context: _ClientContext, body: dict[str, Any], label: str) -> httpx.Response:
    url = f"{BASE_URL}{_MESSAGES_PATH}"
    try:
        return context.client.post(url, headers=context.headers, json=body)
    except httpx.TransportError as exc:
        kind = classify_transport_error(exc=exc)
        raise ProviderUnavailableError(
            kind=kind, provider=label, retry_after_s=None
        ) from exc


def _raise_for_status(response: httpx.Response, label: str) -> None:
    if response.is_success:
        return
    kind, retry_after_s = classify_http_failure(
        status=response.status_code, headers=response.headers
    )
    raise ProviderUnavailableError(
        kind=kind, provider=label, retry_after_s=retry_after_s
    )


def _log_usage(request: ChatRequest, data: dict[str, Any], latency_ms: int) -> None:
    usage = data.get("usage", {})
    logger.info(
        "provider=%s model=%s prompt_tokens=%s output_tokens=%s latency_ms=%d",
        _PROVIDER_LABEL,
        request.model,
        usage.get("input_tokens"),
        usage.get("output_tokens"),
        latency_ms,
    )


def _extract_text(data: dict[str, Any], label: str) -> str:
    try:
        blocks = data["content"]
        text = "".join(block["text"] for block in blocks if block.get("type") == "text")
    # AttributeError: a string or object `content` iterates as characters/keys.
    except (KeyError, TypeError, AttributeError) as exc:
        raise InvalidResponseError(f"{label}: risposta non valida") from exc
    if not text:
        raise InvalidResponseError(f"{label}: contenuto vuoto")
    return text


def _parse_reply(
    request: ChatRequest, response: httpx.Response, latency_ms: int
) -> str:
    label = f"{_PROVIDER_LABEL}/{request.model}"
    try:
        data = response.json()
    except ValueError as exc:
        raise InvalidResponseError(f"{label}: corpo non JSON") from exc
    text = _extract_text(data=data, label=label)
    truncated = data.get("stop_reason") == _TRUNCATED_STOP_REASON
    _log_usage(request=request, data=data, latency_ms=latency_ms)
    if truncated:
        logger.warning("Risposta di %s troncata al limite di token in uscita", label)
    return repair_json_reply(raw=text, truncated=truncated)


def _chat(context: _ClientContext, request: ChatRequest) -> str:
    label = f"{_PROVIDER_LABEL}/{request.model}"
    use_schema = not context.state.is_unsupported(model=request.model)
    start = time.monotonic()
    response = _post(
        context=context,
        body=_build_body(request=request, use_schema=use_schema),
        label=label,
    )
    if response.status_code == _BAD_REQUEST_STATUS and use_schema:
        context.state.mark_unsupported(model=request.model)
        fallback_body = _build_body(request=request, use_schema=False)
        response = _post(context=context, body=fallback_body, label=label)
    _raise_for_status(response=response, label=label)
    latency_ms = int((time.monotonic() - start) * 1000)
    return _parse_reply(request=request, response=response, latency_ms=latency_ms)


def make_anthropic_client(
    api_key: str,
    timeout_s: float,
    transport: httpx.BaseTransport | None = None,
) -> ChatClient:
    """Return a ``ChatClient`` that calls the Anthropic Messages API.

    Parameters
    ----------
    api_key : str
        Sent only in the ``x-api-key`` header, never in the URL.
    timeout_s : float
        Per-request timeout.
    transport : httpx.BaseTransport | None
        Injected transport (``httpx.MockTransport`` in tests); the real
        network is used when omitted.
    """
    context = _ClientContext(
        client=httpx.Client(timeout=timeout_s, transport=transport),
        state=_SchemaFallbackState(),
        headers=_headers(api_key=api_key),
    )

    def _call(request: ChatRequest) -> str:
        return _chat(context=context, request=request)

    return _call


def list_models(
    api_key: str,
    timeout_s: float,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """Raise ``ProviderUnavailableError`` unless Anthropic accepts ``api_key``."""
    label = f"{_PROVIDER_LABEL}/models"
    headers = _headers(api_key=api_key)
    with httpx.Client(timeout=timeout_s, transport=transport) as client:
        try:
            response = client.get(f"{BASE_URL}{_MODELS_PATH}", headers=headers)
        except httpx.TransportError as exc:
            kind = classify_transport_error(exc=exc)
            raise ProviderUnavailableError(
                kind=kind, provider=label, retry_after_s=None
            ) from exc
    _raise_for_status(response=response, label=label)

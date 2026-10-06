"""OpenAI-compatible chat adapter: OpenAI, Groq, and Gemini (A1/A2 of adr.md).

All three speak the same `/chat/completions` shape, verified on their own
docs (adr.md Verifiche eseguite): the token-limit parameter name and
whether `temperature` is accepted differ per provider (`ProviderProfile`).
A model that rejects `response_format: json_schema` answers 400 (Groq's
`strict: false`, Gemini's JSON Schema subset, R2): the client retries once
with `json_object` and remembers the model for every later request on the
same client instance (R2, R4 cooldown is the chain's job, not this one).
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

_CHAT_COMPLETIONS_PATH = "/chat/completions"
_MODELS_PATH = "/models"
_BAD_REQUEST_STATUS = 400


@dataclass(frozen=True, kw_only=True)
class ProviderProfile:
    """Capabilities of one OpenAI-compatible provider.

    Parameters
    ----------
    name : str
        Short identifier used in labels and logs (``"groq"``, not a model).
    base_url : str
        API root, without a trailing slash.
    token_param : str
        Request field for the output-token limit: UNVERIFIED for Groq and
        Gemini (adr.md), confirmed for OpenAI.
    send_temperature : bool
        Whether ``temperature: 0`` is sent. False for OpenAI: its reasoning
        models reject the field with a 400.
    """

    name: str
    base_url: str
    token_param: str
    send_temperature: bool


PROFILES: dict[str, ProviderProfile] = {
    "openai": ProviderProfile(
        name="openai",
        base_url="https://api.openai.com/v1",
        token_param="max_completion_tokens",
        send_temperature=False,
    ),
    "groq": ProviderProfile(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        token_param="max_completion_tokens",  # UNVERIFIED (adr.md)
        send_temperature=True,
    ),
    "gemini": ProviderProfile(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        token_param="max_tokens",  # UNVERIFIED (adr.md)
        send_temperature=True,
    ),
}


class _SchemaFallbackState:
    """Models observed to reject ``json_schema``, learned once per client."""

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
    profile: ProviderProfile
    state: _SchemaFallbackState
    headers: dict[str, str]


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _response_format(use_schema: bool, schema: dict[str, Any]) -> dict[str, Any]:
    if not use_schema:
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "response",
            "strict": False,
            "schema": portable_schema(schema=schema),
        },
    }


def _build_body(
    profile: ProviderProfile, request: ChatRequest, use_schema: bool
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": request.model,
        "messages": [
            {"role": "system", "content": request.system_prompt},
            {"role": "user", "content": request.user_message},
        ],
        "response_format": _response_format(
            use_schema=use_schema, schema=request.schema
        ),
    }
    if profile.send_temperature:
        body["temperature"] = 0
    if request.num_predict is not None:
        body[profile.token_param] = request.num_predict
    return body


def _post(
    context: _ClientContext, url: str, body: dict[str, Any], label: str
) -> httpx.Response:
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


def _log_usage(
    context: _ClientContext, request: ChatRequest, data: dict[str, Any], latency_ms: int
) -> None:
    usage = data.get("usage", {})
    logger.info(
        "provider=%s model=%s prompt_tokens=%s output_tokens=%s latency_ms=%d",
        context.profile.name,
        request.model,
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
        latency_ms,
    )


def _parse_reply(
    context: _ClientContext,
    request: ChatRequest,
    response: httpx.Response,
    latency_ms: int,
) -> str:
    label = f"{context.profile.name}/{request.model}"
    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        finish_reason = data["choices"][0]["finish_reason"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise InvalidResponseError(f"{label}: risposta non valida") from exc
    if not content:
        raise InvalidResponseError(f"{label}: contenuto vuoto")
    truncated = finish_reason == "length"
    _log_usage(context=context, request=request, data=data, latency_ms=latency_ms)
    if truncated:
        logger.warning("Risposta di %s troncata al limite di token in uscita", label)
    return repair_json_reply(raw=content, truncated=truncated)


def _chat(context: _ClientContext, request: ChatRequest) -> str:
    label = f"{context.profile.name}/{request.model}"
    use_schema = not context.state.is_unsupported(model=request.model)
    url = f"{context.profile.base_url}{_CHAT_COMPLETIONS_PATH}"
    start = time.monotonic()
    body = _build_body(profile=context.profile, request=request, use_schema=use_schema)
    response = _post(context=context, url=url, body=body, label=label)
    if response.status_code == _BAD_REQUEST_STATUS and use_schema:
        context.state.mark_unsupported(model=request.model)
        fallback_body = _build_body(
            profile=context.profile, request=request, use_schema=False
        )
        response = _post(context=context, url=url, body=fallback_body, label=label)
    _raise_for_status(response=response, label=label)
    latency_ms = int((time.monotonic() - start) * 1000)
    return _parse_reply(
        context=context, request=request, response=response, latency_ms=latency_ms
    )


def make_openai_compat_client(
    profile: ProviderProfile,
    api_key: str,
    timeout_s: float,
    transport: httpx.BaseTransport | None = None,
) -> ChatClient:
    """Return a ``ChatClient`` that talks to ``profile`` over HTTP.

    Parameters
    ----------
    profile : ProviderProfile
        Which provider (base URL and capabilities) to call.
    api_key : str
        Sent only in the ``Authorization`` header, never in the URL.
    timeout_s : float
        Per-request timeout.
    transport : httpx.BaseTransport | None
        Injected transport (``httpx.MockTransport`` in tests); the real
        network is used when omitted.
    """
    context = _ClientContext(
        client=httpx.Client(timeout=timeout_s, transport=transport),
        profile=profile,
        state=_SchemaFallbackState(),
        headers=_headers(api_key=api_key),
    )

    def _call(request: ChatRequest) -> str:
        return _chat(context=context, request=request)

    return _call


def list_models(
    profile: ProviderProfile,
    api_key: str,
    timeout_s: float,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """Raise ``ProviderUnavailableError`` unless ``profile`` accepts ``api_key``."""
    label = f"{profile.name}/models"
    url = f"{profile.base_url}{_MODELS_PATH}"
    headers = _headers(api_key=api_key)
    with httpx.Client(timeout=timeout_s, transport=transport) as client:
        try:
            response = client.get(url, headers=headers)
        except httpx.TransportError as exc:
            kind = classify_transport_error(exc=exc)
            raise ProviderUnavailableError(
                kind=kind, provider=label, retry_after_s=None
            ) from exc
    _raise_for_status(response=response, label=label)

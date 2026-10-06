"""Check a saved API key with a call that generates no tokens (T035).

LLM providers list their models; AssemblyAI lists one transcript. A key the
provider rejects is "auth"; an unreachable provider is "network"; anything
else ("limit", "server") is reported without hiding it behind "ok".
"""

from typing import Literal

import httpx

from sbobina.llm_errors import (
    FailureKind,
    ProviderUnavailableError,
    classify_http_failure,
    classify_transport_error,
)
from sbobina.providers import anthropic, openai_compat

type KeyCheckResult = Literal["ok", "missing", "auth", "network", "limit", "error"]

# UNVERIFIED: "List transcripts" is documented as GET /v2/transcript; a
# limit of 1 keeps the reply small. To be confirmed in T050.
_ASSEMBLYAI_LIST_URL = "https://api.assemblyai.com/v2/transcript?limit=1"
_RESULT_BY_KIND: dict[FailureKind, KeyCheckResult] = {
    FailureKind.AUTH: "auth",
    FailureKind.NETWORK: "network",
    FailureKind.TIMEOUT: "network",
    FailureKind.RATE_LIMIT: "limit",
    FailureKind.QUOTA: "limit",
}


def _check_assemblyai(
    api_key: str, timeout_s: float, transport: httpx.BaseTransport | None
) -> None:
    headers = {"authorization": api_key}
    with httpx.Client(timeout=timeout_s, transport=transport) as client:
        try:
            response = client.get(_ASSEMBLYAI_LIST_URL, headers=headers)
        except httpx.TransportError as exc:
            kind = classify_transport_error(exc=exc)
            raise ProviderUnavailableError(
                kind=kind, provider="assemblyai", retry_after_s=None
            ) from exc
    if response.is_success:
        return
    kind, retry_after_s = classify_http_failure(
        status=response.status_code, headers=response.headers
    )
    raise ProviderUnavailableError(
        kind=kind, provider="assemblyai", retry_after_s=retry_after_s
    )


def _call_provider(
    provider: str,
    api_key: str,
    timeout_s: float,
    transport: httpx.BaseTransport | None,
) -> None:
    if provider == "anthropic":
        anthropic.list_models(api_key=api_key, timeout_s=timeout_s, transport=transport)
    elif provider == "assemblyai":
        _check_assemblyai(api_key=api_key, timeout_s=timeout_s, transport=transport)
    else:
        openai_compat.list_models(
            profile=openai_compat.PROFILES[provider],
            api_key=api_key,
            timeout_s=timeout_s,
            transport=transport,
        )


def check_key(
    provider: str,
    api_key: str | None,
    timeout_s: float,
    transport: httpx.BaseTransport | None = None,
) -> KeyCheckResult:
    """Classify whether `provider` accepts `api_key` right now."""
    if not api_key:
        return "missing"
    try:
        _call_provider(
            provider=provider, api_key=api_key, timeout_s=timeout_s, transport=transport
        )
    except ProviderUnavailableError as error:
        return _RESULT_BY_KIND.get(error.kind, "error")
    return "ok"

"""Failure taxonomy shared by every LLM provider, local or cloud.

Classification is pure: it turns an HTTP status/headers pair or a transport
exception into a `FailureKind`, with no I/O. The chain policy (not this
module) decides what each kind means for a link's eligibility.
"""

from collections.abc import Mapping
from enum import StrEnum

import httpx

from sbobina.correction import CorrectorUnavailableError

_AUTH_STATUSES = frozenset({401, 403})
_MODEL_MISSING_STATUS = 404
_RATE_LIMIT_STATUS = 429
_QUOTA_STATUS = 402
_BAD_REQUEST_STATUSES = frozenset({400, 422})
_REQUEST_TIMEOUT_STATUS = 408


class FailureKind(StrEnum):
    """Why a provider could not serve a request, independent of its API."""

    AUTH = "auth"
    QUOTA = "quota"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NETWORK = "network"
    SERVER = "server"
    BAD_REQUEST = "bad_request"
    MISSING_KEY = "missing_key"
    MODEL_MISSING = "model_missing"
    BUSY = "busy"


_KIND_LABELS_IT: dict[FailureKind, str] = {
    FailureKind.AUTH: "chiave non valida",
    FailureKind.QUOTA: "quota esaurita",
    FailureKind.RATE_LIMIT: "limite raggiunto",
    FailureKind.TIMEOUT: "timeout",
    FailureKind.NETWORK: "non raggiungibile",
    FailureKind.SERVER: "errore del servizio",
    FailureKind.BAD_REQUEST: "richiesta rifiutata",
    FailureKind.MISSING_KEY: "chiave assente",
    FailureKind.MODEL_MISSING: "modello non installato",
    FailureKind.BUSY: "GPU occupata dalla trascrizione",
}


class ProviderUnavailableError(CorrectorUnavailableError):
    """One chain link could not serve a request.

    Parameters
    ----------
    kind : FailureKind
        Why the link failed.
    provider : str
        The ``provider/model`` identifier of the link.
    retry_after_s : float | None
        Seconds the caller should wait before retrying this link, when the
        provider stated one.
    """

    def __init__(
        self, kind: FailureKind, provider: str, retry_after_s: float | None
    ) -> None:
        self.kind = kind
        self.provider = provider
        self.retry_after_s = retry_after_s
        super().__init__(f"{provider}: {_KIND_LABELS_IT[kind]}")


class ChainExhaustedError(CorrectorUnavailableError):
    """No link in the fallback chain could serve the request.

    Parameters
    ----------
    causes : tuple[ProviderUnavailableError, ...]
        The failure of every link, in the order they were tried.
    """

    def __init__(self, causes: tuple[ProviderUnavailableError, ...]) -> None:
        self.causes = causes
        reasons = ", ".join(
            f"{cause.provider} ({_KIND_LABELS_IT[cause.kind]})" for cause in causes
        )
        super().__init__(f"Nessun modello disponibile: {reasons}")


def _retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    value = headers.get("Retry-After")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def classify_http_failure(
    status: int, headers: Mapping[str, str]
) -> tuple[FailureKind, float | None]:
    """Map an HTTP response's status and headers to a failure kind.

    No response body is read: the classification uses only the status
    code and, for ``429``, the ``Retry-After`` header.
    """
    if status in _AUTH_STATUSES:
        return FailureKind.AUTH, None
    if status == _MODEL_MISSING_STATUS:
        return FailureKind.MODEL_MISSING, None
    if status == _RATE_LIMIT_STATUS:
        return FailureKind.RATE_LIMIT, _retry_after_seconds(headers=headers)
    if status == _QUOTA_STATUS:
        return FailureKind.QUOTA, None
    if status in _BAD_REQUEST_STATUSES:
        return FailureKind.BAD_REQUEST, None
    if status == _REQUEST_TIMEOUT_STATUS:
        return FailureKind.TIMEOUT, None
    # Anything else (413, 409, 3xx, >= 500) must still move the chain on:
    # a raise here would escape FallbackChain and stop the whole job.
    return FailureKind.SERVER, None


def classify_transport_error(exc: Exception) -> FailureKind:
    """Map a transport-level exception to a failure kind.

    ``httpx.TimeoutException`` is checked before ``httpx.TransportError``
    because it is a subclass of it.
    """
    if isinstance(exc, httpx.TimeoutException):
        return FailureKind.TIMEOUT
    if isinstance(exc, httpx.TransportError | ConnectionError):
        return FailureKind.NETWORK
    raise TypeError(f"Unclassified transport error: {type(exc).__name__}") from exc

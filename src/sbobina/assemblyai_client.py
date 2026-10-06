"""The only HTTP boundary towards AssemblyAI (T052).

Verified on the official docs (adr.md § Verifiche eseguite): upload to
`/v2/upload` (max 2.2 GB), submit to `/v2/transcript`, poll until
`completed`/`error`, read `/sentences`, then `DELETE /v2/transcript/{id}`,
which also deletes the uploaded file. The key travels only in the
`authorization` header.
"""

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from sbobina.llm_errors import (
    FailureKind,
    ProviderUnavailableError,
    classify_http_failure,
    classify_transport_error,
)

PROVIDER = "assemblyai"
BASE_URL = "https://api.assemblyai.com"
SPEECH_MODELS = ("universal-3-5-pro", "universal-2")
MAX_UPLOAD_BYTES = 2_200_000_000
_UPLOAD_CHUNK_BYTES = 1 << 20
_POLL_INTERVAL_S = 5.0
_MIN_WAIT_S = 900.0
_TERMINAL_OK = "completed"
_TERMINAL_ERROR = "error"
_TRANSIENT_KINDS = frozenset(
    {FailureKind.NETWORK, FailureKind.TIMEOUT, FailureKind.SERVER}
)

type UploadProgress = Callable[[int, int], None]


class RemoteTranscriptionError(Exception):
    """AssemblyAI reported the transcription as failed; its reason is kept."""


@dataclass(frozen=True, kw_only=True)
class ClientConfig:
    api_key: str
    request_timeout_s: float = 60.0
    poll_interval_s: float = _POLL_INTERVAL_S
    transport: httpx.BaseTransport | None = None
    sleep: Callable[[float], None] = field(default=time.sleep)
    now: Callable[[], float] = field(default=time.monotonic)


def _raise_for(response: httpx.Response) -> None:
    if response.is_success:
        return
    kind, retry_after_s = classify_http_failure(
        status=response.status_code, headers=response.headers
    )
    raise ProviderUnavailableError(
        kind=kind, provider=PROVIDER, retry_after_s=retry_after_s
    )


def _read_chunks(path: Path, on_progress: UploadProgress) -> Iterator[bytes]:
    total = path.stat().st_size
    sent = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_UPLOAD_CHUNK_BYTES):
            sent += len(chunk)
            on_progress(sent, total)
            yield chunk


class AssemblyAIClient:
    def __init__(self, config: ClientConfig) -> None:
        self._config = config
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"authorization": config.api_key},
            timeout=config.request_timeout_s,
            transport=config.transport,
        )

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._http.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            kind = classify_transport_error(exc=exc)
            raise ProviderUnavailableError(
                kind=kind, provider=PROVIDER, retry_after_s=None
            ) from exc
        _raise_for(response=response)
        return response

    def upload(self, audio_path: Path, on_progress: UploadProgress) -> str:
        """Stream the file from disk; return the private `upload_url`."""
        if audio_path.stat().st_size > MAX_UPLOAD_BYTES:
            raise RemoteTranscriptionError("File troppo grande per AssemblyAI (2,2 GB)")
        chunks = _read_chunks(path=audio_path, on_progress=on_progress)
        response = self._request("POST", "/v2/upload", content=chunks)
        return str(response.json()["upload_url"])

    def submit(self, upload_url: str, language: str) -> str:
        body = {
            "audio_url": upload_url,
            "language_code": language,
            "speech_models": list(SPEECH_MODELS),
        }
        return str(self._request("POST", "/v2/transcript", json=body).json()["id"])

    def _poll_once(self, transcript_id: str) -> dict[str, Any] | None:
        try:
            reply: dict[str, Any] = self._request(
                "GET", f"/v2/transcript/{transcript_id}"
            ).json()
        except ProviderUnavailableError as error:
            if error.kind in _TRANSIENT_KINDS:
                return None  # the remote job keeps running: try again later
            raise
        return reply

    def wait(self, transcript_id: str, max_wait_s: float) -> dict[str, Any]:
        """Poll until the transcript is done; transient errors are retried."""
        deadline = self._config.now() + max(max_wait_s, _MIN_WAIT_S)
        while self._config.now() < deadline:
            reply = self._poll_once(transcript_id=transcript_id)
            status = reply.get("status") if reply is not None else None
            if status == _TERMINAL_OK and reply is not None:
                return reply
            if status == _TERMINAL_ERROR and reply is not None:
                reason = str(reply.get("error") or "motivo non indicato")
                raise RemoteTranscriptionError(f"AssemblyAI: {reason}")
            self._config.sleep(self._config.poll_interval_s)
        raise ProviderUnavailableError(
            kind=FailureKind.TIMEOUT, provider=PROVIDER, retry_after_s=None
        )

    def sentences(self, transcript_id: str) -> dict[str, Any]:
        reply: dict[str, Any] = self._request(
            "GET", f"/v2/transcript/{transcript_id}/sentences"
        ).json()
        return reply

    def delete(self, transcript_id: str) -> None:
        """Delete the transcript and the uploaded audio on the service."""
        self._request("DELETE", f"/v2/transcript/{transcript_id}")

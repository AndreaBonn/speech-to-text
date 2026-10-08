from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from sbobina import assemblyai_client
from sbobina.assemblyai_client import (
    AssemblyAIClient,
    ClientConfig,
    RemoteTranscriptionError,
)
from sbobina.llm_errors import FailureKind, ProviderUnavailableError

SENTINEL_KEY = "aai-SENTINEL-0123456789abcdef"
SENTENCES: dict[str, list[object]] = {"sentences": []}

type Handler = Callable[[httpx.Request], httpx.Response]


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def _client(handler: Handler, clock: FakeClock | None = None) -> AssemblyAIClient:
    clock = clock or FakeClock()
    return AssemblyAIClient(
        config=ClientConfig(
            api_key=SENTINEL_KEY,
            transport=httpx.MockTransport(handler),
            sleep=clock.sleep,
            now=clock.now,
        )
    )


def _poll_handler(statuses: list[httpx.Response], seen: list[httpx.Request]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return statuses.pop(0)

    return handler


def test_upload_streams_the_file_and_reports_progress(tmp_path: Path) -> None:
    audio = tmp_path / "lezione.m4a"
    audio.write_bytes(b"x" * 10)
    seen: list[httpx.Request] = []
    progress: list[tuple[int, int]] = []
    handler = _poll_handler(
        [httpx.Response(200, json={"upload_url": "https://cdn/up"})], seen
    )

    url = _client(handler).upload(
        audio_path=audio, on_progress=lambda sent, total: progress.append((sent, total))
    )

    assert url == "https://cdn/up"
    assert progress[-1] == (10, 10)
    assert seen[0].headers["authorization"] == SENTINEL_KEY
    assert SENTINEL_KEY not in str(seen[0].url)


def test_upload_rejects_a_file_over_the_service_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "lezione.m4a"
    audio.write_bytes(b"x" * 10)
    monkeypatch.setattr(assemblyai_client, "MAX_UPLOAD_BYTES", 5)
    seen: list[httpx.Request] = []

    with pytest.raises(RemoteTranscriptionError):
        _client(_poll_handler([], seen)).upload(
            audio_path=audio, on_progress=lambda sent, total: None
        )
    assert seen == []


def test_submit_sends_language_and_speech_models() -> None:
    seen: list[httpx.Request] = []
    handler = _poll_handler([httpx.Response(200, json={"id": "t1"})], seen)

    transcript_id = _client(handler).submit(upload_url="https://cdn/up", language="it")

    assert transcript_id == "t1"
    body = seen[0].read().decode()
    assert '"language_code":"it"' in body.replace(" ", "")
    assert "universal-3-5-pro" in body


def test_wait_polls_until_completed() -> None:
    clock = FakeClock()
    seen: list[httpx.Request] = []
    handler = _poll_handler(
        [
            httpx.Response(200, json={"status": "queued"}),
            httpx.Response(503),
            httpx.Response(200, json={"status": "processing"}),
            httpx.Response(200, json={"status": "completed", "audio_duration": 9}),
        ],
        seen,
    )

    reply = _client(handler, clock).wait(transcript_id="t1", max_wait_s=60)

    assert reply["audio_duration"] == 9
    assert len(clock.sleeps) == 3


def test_wait_remote_error_keeps_the_reason() -> None:
    handler = _poll_handler(
        [httpx.Response(200, json={"status": "error", "error": "audio corrotto"})], []
    )

    with pytest.raises(RemoteTranscriptionError, match="audio corrotto"):
        _client(handler).wait(transcript_id="t1", max_wait_s=60)


def test_wait_gives_up_after_the_deadline() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "processing"})

    with pytest.raises(ProviderUnavailableError) as excinfo:
        _client(handler).wait(transcript_id="t1", max_wait_s=0)

    assert excinfo.value.kind == FailureKind.TIMEOUT


def test_wait_unauthorized_is_not_retried() -> None:
    seen: list[httpx.Request] = []
    handler = _poll_handler([httpx.Response(401, json={"error": "bad key"})], seen)

    with pytest.raises(ProviderUnavailableError) as excinfo:
        _client(handler).wait(transcript_id="t1", max_wait_s=60)

    assert excinfo.value.kind == FailureKind.AUTH
    assert len(seen) == 1
    assert SENTINEL_KEY not in str(excinfo.value)


def test_sentences_and_delete_hit_the_transcript_endpoints() -> None:
    seen: list[httpx.Request] = []
    handler = _poll_handler(
        [httpx.Response(200, json=SENTENCES), httpx.Response(200, json={})], seen
    )
    client = _client(handler)

    assert client.sentences(transcript_id="t1") == SENTENCES
    client.delete(transcript_id="t1")

    assert [(r.method, r.url.path) for r in seen] == [
        ("GET", "/v2/transcript/t1/sentences"),
        ("DELETE", "/v2/transcript/t1"),
    ]


def test_close_prevents_further_requests() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json=SENTENCES)

    client = _client(handler=handler)
    assert client.sentences(transcript_id="t1") == SENTENCES

    client.close()

    with pytest.raises(RuntimeError, match="client has been closed"):
        client.sentences(transcript_id="t1")


@pytest.mark.parametrize(
    ("error_type", "expected"),
    [
        (httpx.ConnectError, FailureKind.NETWORK),
        (httpx.ReadTimeout, FailureKind.TIMEOUT),
    ],
)
def test_sentences_transport_failure_preserves_kind(
    error_type: type[httpx.TransportError], expected: FailureKind
) -> None:
    failure = error_type("connection failed")

    def handler(request: httpx.Request) -> httpx.Response:
        raise failure

    client = _client(handler=handler)
    try:
        with pytest.raises(ProviderUnavailableError) as excinfo:
            client.sentences(transcript_id="t1")
    finally:
        client.close()

    assert excinfo.value.kind == expected
    assert excinfo.value.provider == "assemblyai"
    assert excinfo.value.retry_after_s is None
    assert excinfo.value.__cause__ is failure


def test_wait_on_poll_receives_elapsed_seconds() -> None:
    clock = FakeClock()
    clock.t = 100.0
    seen: list[httpx.Request] = []
    elapsed: list[float] = []
    handler = _poll_handler(
        statuses=[
            httpx.Response(status_code=200, json={"status": "queued"}),
            httpx.Response(status_code=503),
            httpx.Response(status_code=200, json={"status": "completed"}),
        ],
        seen=seen,
    )
    client = _client(handler=handler, clock=clock)
    try:
        reply = client.wait(transcript_id="t1", max_wait_s=900, on_poll=elapsed.append)
    finally:
        client.close()

    assert reply == {"status": "completed"}
    assert elapsed == [0.0, 5.0, 10.0]
    assert len(seen) == 3

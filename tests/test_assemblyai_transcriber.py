import json
import logging
from pathlib import Path
from typing import Any, ClassVar

import httpx
import pytest
from pydantic import SecretStr

from sbobina import assemblyai_transcriber, pipeline
from sbobina.assemblyai_client import ClientConfig, RemoteTranscriptionError
from sbobina.llm_errors import FailureKind, ProviderUnavailableError
from sbobina.models import load_transcript
from sbobina.notices import USER_NOTICE
from sbobina.settings import Settings

SENTINEL_KEY = "aai-SENTINEL-0123456789abcdef"
SENTENCES = {
    "sentences": [
        {
            "start": 0,
            "end": 900,
            "words": [
                {"text": "Buongiorno.", "start": 0, "end": 900, "confidence": 0.9}
            ],
        }
    ]
}


class FakeClient:
    instances: ClassVar[list["FakeClient"]] = []

    def __init__(self, config: ClientConfig) -> None:
        self.config = config
        self.calls: list[str] = []
        self.wait_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.submit_error: Exception | None = None
        FakeClient.instances.append(self)

    def upload(self, audio_path: Path, on_progress: Any) -> str:
        self.calls.append("upload")
        on_progress(10, 10)
        return "https://cdn/up"

    def submit(self, upload_url: str, language: str) -> str:
        self.calls.append(f"submit:{language}")
        if self.submit_error is not None:
            raise self.submit_error
        return "t1"

    def wait(
        self, transcript_id: str, max_wait_s: float, on_poll: Any = None
    ) -> dict[str, Any]:
        self.calls.append("wait")
        if on_poll is not None:
            on_poll(300.0)
        if self.wait_error is not None:
            raise self.wait_error
        return {"status": "completed", "audio_duration": 1, "speech_model_used": "u3"}

    def sentences(self, transcript_id: str) -> dict[str, Any]:
        self.calls.append("sentences")
        return SENTENCES

    def delete(self, transcript_id: str) -> None:
        self.calls.append("delete")
        if self.delete_error is not None:
            raise self.delete_error

    def close(self) -> None:
        self.calls.append("close")


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> type[FakeClient]:
    FakeClient.instances = []
    monkeypatch.setattr(assemblyai_transcriber, "AssemblyAIClient", FakeClient)
    return FakeClient


def _config() -> Settings:
    return Settings(
        assemblyai_api_key=SecretStr(SENTINEL_KEY), transcription_engine="assemblyai"
    )


@pytest.fixture
def remote_http(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[httpx.Request], list[str]]:
    requests: list[httpx.Request] = []
    events: list[str] = []
    replies = {
        ("POST", "/v2/upload"): {"upload_url": "https://cdn/up"},
        ("POST", "/v2/transcript"): {"id": "t1"},
        ("GET", "/v2/transcript/t1"): {
            "status": "completed",
            "audio_duration": 1,
            "speech_model_used": "u3",
        },
        ("GET", "/v2/transcript/t1/sentences"): SENTENCES,
        ("DELETE", "/v2/transcript/t1"): {},
    }

    def handle_request(
        self: httpx.HTTPTransport, request: httpx.Request
    ) -> httpx.Response:
        request.read()
        requests.append(request)
        events.append(request.method)
        return httpx.Response(200, json=replies[(request.method, request.url.path)])

    def close(self: httpx.HTTPTransport) -> None:
        events.append("close")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle_request)
    monkeypatch.setattr(httpx.HTTPTransport, "close", close)
    return requests, events


def test_transcribe_file_completed_response_converts_transcript(
    remote_http: tuple[list[httpx.Request], list[str]], tmp_path: Path
) -> None:
    audio_path = tmp_path / "a.m4a"
    audio_path.write_bytes(b"audio")

    transcript = assemblyai_transcriber.transcribe_file(
        audio_path=audio_path, config=_config()
    )

    assert transcript.model == "assemblyai:u3"
    assert transcript.segments[0].text == "Buongiorno."


def test_transcribe_file_completed_response_deletes_and_closes(
    remote_http: tuple[list[httpx.Request], list[str]], tmp_path: Path
) -> None:
    audio_path = tmp_path / "a.m4a"
    audio_path.write_bytes(b"audio")

    assemblyai_transcriber.transcribe_file(audio_path=audio_path, config=_config())

    requests, events = remote_http
    assert (requests[-1].method, requests[-1].url.path) == (
        "DELETE",
        "/v2/transcript/t1",
    )
    delete_index = events.index("DELETE")
    assert events[delete_index + 1 :]
    assert set(events[delete_index + 1 :]) == {"close"}


def test_transcribe_file_completed_response_finishes_progress(
    remote_http: tuple[list[httpx.Request], list[str]], tmp_path: Path
) -> None:
    audio_path = tmp_path / "a.m4a"
    audio_path.write_bytes(b"audio")
    progress: list[tuple[float, float]] = []

    assemblyai_transcriber.transcribe_file(
        audio_path=audio_path,
        config=_config(),
        on_progress=lambda done, total: progress.append((done, total)),
    )

    assert progress[-1] == (1.0, 1.0)


def test_transcribe_file_italian_config_submits_language(
    remote_http: tuple[list[httpx.Request], list[str]], tmp_path: Path
) -> None:
    audio_path = tmp_path / "a.m4a"
    audio_path.write_bytes(b"audio")

    assemblyai_transcriber.transcribe_file(audio_path=audio_path, config=_config())

    requests, _ = remote_http
    submission = next(
        r for r in requests if r.method == "POST" and r.url.path == "/v2/transcript"
    )
    assert json.loads(submission.content)["language_code"] == "it"


def test_transcribe_file_remote_error_still_deletes(
    fake_client: type[FakeClient], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_init = FakeClient.__init__

    def failing_init(self: FakeClient, config: ClientConfig) -> None:
        original_init(self, config)
        self.wait_error = RemoteTranscriptionError("AssemblyAI: audio corrotto")

    monkeypatch.setattr(FakeClient, "__init__", failing_init)

    with pytest.raises(RemoteTranscriptionError, match="audio corrotto"):
        assemblyai_transcriber.transcribe_file(tmp_path / "a.m4a", config=_config())
    assert "delete" in fake_client.instances[0].calls


def test_transcribe_file_failed_delete_is_a_user_notice(
    fake_client: type[FakeClient],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    original_init = FakeClient.__init__

    def failing_delete(self: FakeClient, config: ClientConfig) -> None:
        original_init(self, config)
        self.delete_error = ProviderUnavailableError(
            kind=FailureKind.SERVER, provider="assemblyai", retry_after_s=None
        )

    monkeypatch.setattr(FakeClient, "__init__", failing_delete)

    with caplog.at_level(logging.WARNING):
        assemblyai_transcriber.transcribe_file(tmp_path / "a.m4a", config=_config())

    notices = [r for r in caplog.records if getattr(r, USER_NOTICE, False)]
    assert "t1" in notices[0].getMessage()
    assert SENTINEL_KEY not in caplog.text


def test_transcribe_file_without_key_fails_before_any_upload(
    fake_client: type[FakeClient], tmp_path: Path
) -> None:
    with pytest.raises(ProviderUnavailableError) as excinfo:
        assemblyai_transcriber.transcribe_file(
            tmp_path / "a.m4a", config=Settings(transcription_engine="assemblyai")
        )

    assert excinfo.value.kind == FailureKind.MISSING_KEY
    assert fake_client.instances == []


def test_transcribe_to_dir_assemblyai_persists_remote_model(
    remote_http: tuple[list[httpx.Request], list[str]], tmp_path: Path
) -> None:
    audio = tmp_path / "lezione.m4a"
    audio.write_bytes(b"x")

    json_path = pipeline.transcribe_to_dir(
        audio_path=audio, output_dir=tmp_path / "out", config=_config()
    )

    transcript = load_transcript(path=json_path)
    assert transcript.model == "assemblyai:u3"


def test_transcribe_file_reports_progress_while_waiting_remotely(
    fake_client: type[FakeClient], tmp_path: Path
) -> None:
    progress: list[float] = []

    assemblyai_transcriber.transcribe_file(
        tmp_path / "a.m4a",
        config=_config(),
        on_progress=lambda d, t: progress.append(d),
    )

    remote = [value for value in progress if 0.3 < value < 0.9]
    assert remote == [pytest.approx(0.6)]


def test_transcribe_file_failed_submit_warns_about_the_orphan_upload(
    fake_client: type[FakeClient],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    original_init = FakeClient.__init__

    def failing_submit(self: FakeClient, config: ClientConfig) -> None:
        original_init(self, config)
        self.submit_error = ProviderUnavailableError(
            kind=FailureKind.SERVER, provider="assemblyai", retry_after_s=None
        )

    monkeypatch.setattr(FakeClient, "__init__", failing_submit)

    with caplog.at_level(logging.WARNING), pytest.raises(ProviderUnavailableError):
        assemblyai_transcriber.transcribe_file(tmp_path / "a.m4a", config=_config())

    notices = [r for r in caplog.records if getattr(r, USER_NOTICE, False)]
    assert "non avviata" in notices[0].getMessage()
    assert "delete" not in fake_client.instances[0].calls

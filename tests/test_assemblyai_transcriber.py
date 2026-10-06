import logging
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import SecretStr

from sbobina import assemblyai_transcriber, pipeline
from sbobina.assemblyai_client import ClientConfig, RemoteTranscriptionError
from sbobina.llm_errors import FailureKind, ProviderUnavailableError
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
        FakeClient.instances.append(self)

    def upload(self, audio_path: Path, on_progress: Any) -> str:
        self.calls.append("upload")
        on_progress(10, 10)
        return "https://cdn/up"

    def submit(self, upload_url: str, language: str) -> str:
        self.calls.append(f"submit:{language}")
        return "t1"

    def wait(self, transcript_id: str, max_wait_s: float) -> dict[str, Any]:
        self.calls.append("wait")
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


def test_transcribe_file_converts_and_deletes_the_remote_copy(
    fake_client: type[FakeClient], tmp_path: Path
) -> None:
    progress: list[float] = []

    transcript = assemblyai_transcriber.transcribe_file(
        tmp_path / "a.m4a",
        config=_config(),
        on_progress=lambda d, t: progress.append(d),
    )

    client = fake_client.instances[0]
    assert transcript.model == "assemblyai:u3"
    assert transcript.segments[0].text == "Buongiorno."
    assert client.calls[-2:] == ["delete", "close"]
    assert "submit:it" in client.calls
    assert progress[-1] == 1.0


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


def test_transcribe_to_dir_assemblyai_never_loads_whisper(
    fake_client: type[FakeClient], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def whisper_must_not_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("faster-whisper called with the AssemblyAI engine")

    monkeypatch.setattr("sbobina.transcriber.transcribe_file", whisper_must_not_run)
    audio = tmp_path / "lezione.m4a"
    audio.write_bytes(b"x")

    json_path = pipeline.transcribe_to_dir(audio, tmp_path / "out", config=_config())

    assert json_path.exists()
    assert fake_client.instances[0].calls[0] == "upload"

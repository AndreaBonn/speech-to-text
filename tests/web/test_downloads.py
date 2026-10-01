import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import ollama
import pytest
from huggingface_hub.file_download import DryRunFileInfo
from pydantic import ValidationError as PydanticValidationError

from sbobina.settings import Settings
from sbobina.web import downloads
from sbobina.web.errors import ConflictError

HOST = "http://127.0.0.1:11434"


def _wait_until(
    predicate: object, timeout: float = 5.0, interval: float = 0.01
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():  # type: ignore[operator]
            return
        time.sleep(interval)
    raise AssertionError("condition not met in time")


def test_download_request_accepts_known_whisper_model() -> None:
    assert downloads.DownloadRequest(source="whisper", name="tiny").name == "tiny"


def test_download_request_rejects_unknown_whisper_model() -> None:
    with pytest.raises(PydanticValidationError, match="non disponibile"):
        downloads.DownloadRequest(source="whisper", name="not-a-model")


def test_download_request_rejects_blank_name() -> None:
    with pytest.raises(PydanticValidationError, match="non può essere vuoto"):
        downloads.DownloadRequest(source="ollama", name="   ")


def test_download_state_to_json_handles_missing_total() -> None:
    state = downloads.DownloadState(
        source="whisper", name="tiny", status="running", completed=5, total=None
    )
    assert state.to_json()["fraction"] is None


def test_whisper_download_reports_growing_progress_from_partial_blobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Mirrors huggingface_hub 1.33: bytes grow in blobs/<etag>.<uuid>.incomplete,
    # the blob is renamed when complete and the snapshots/ pointer comes last.
    monkeypatch.setattr(downloads, "POLL_INTERVAL_S", 0.01)
    repo = tmp_path / "models--Systran--faster-whisper-tiny"
    blobs = repo / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "already-cached").write_bytes(b"0" * 7)
    pointer = repo / "snapshots" / "x" / "model.bin"
    infos = [
        DryRunFileInfo(
            commit_hash="x",
            file_size=15,
            filename="model.bin",
            local_path=str(pointer),
            is_cached=False,
            will_download=True,
        )
    ]
    halfway = threading.Event()
    release = threading.Event()

    def fake_snapshot(
        *, repo_id: str, allow_patterns: list[str], dry_run: bool = False, **_: object
    ) -> list[DryRunFileInfo] | str:
        if dry_run:
            return infos
        partial = blobs / "etag.1a2b3c4d.incomplete"
        partial.write_bytes(b"0" * 6)
        halfway.set()
        release.wait(timeout=5)
        partial.write_bytes(b"0" * 15)
        partial.rename(blobs / "etag")
        pointer.parent.mkdir(parents=True)
        pointer.symlink_to(blobs / "etag")
        return str(repo)

    with patch.object(downloads, "snapshot_download", side_effect=fake_snapshot):
        manager = downloads.DownloadManager(settings=Settings())
        manager.start(source="whisper", name="tiny")
        halfway.wait(timeout=5)
        _wait_until(lambda: manager.list()[0].completed == 6)
        mid = manager.list()[0]
        release.set()
        manager.join(source="whisper", name="tiny", timeout=5)

    assert (mid.status, mid.completed, mid.total) == ("running", 6, 15)
    final = manager.list()[0]
    assert (final.status, final.completed, final.total) == ("done", 15, 15)


def test_download_threads_do_not_block_shutdown() -> None:
    hold = threading.Event()

    def fake_snapshot(
        *, repo_id: str, allow_patterns: list[str], dry_run: bool = False, **_: object
    ) -> list[DryRunFileInfo] | str:
        if dry_run:
            return []
        hold.wait(timeout=5)
        return ""

    with patch.object(downloads, "snapshot_download", side_effect=fake_snapshot):
        manager = downloads.DownloadManager(settings=Settings())
        manager.start(source="whisper", name="tiny")
        names = {thread.name: thread.daemon for thread in threading.enumerate()}
        hold.set()
        manager.join(source="whisper", name="tiny", timeout=5)

    assert names["download-whisper-tiny"] is True


@pytest.mark.parametrize("name", ["qwen3.5:9b", "library/llama3.2:3b-instruct-q4_K_M"])
def test_download_request_accepts_ollama_names(name: str) -> None:
    assert downloads.DownloadRequest(source="ollama", name=name).name == name


@pytest.mark.parametrize("name", ["bad name", "x" * 201, "a;rm -rf", "../etc"])
def test_download_request_rejects_invalid_ollama_names(name: str) -> None:
    with pytest.raises(PydanticValidationError, match="Nome del modello Ollama"):
        downloads.DownloadRequest(source="ollama", name=name)


def test_finished_states_are_capped() -> None:
    def failing_pull(*, model: str, stream: bool) -> object:
        raise ConnectionError("down")

    client = MagicMock()
    client.__enter__.return_value.pull.side_effect = failing_pull
    with patch.object(ollama, "Client", return_value=client):
        manager = downloads.DownloadManager(settings=Settings())
        for index in range(downloads.MAX_FINISHED_STATES + 10):
            manager.start(source="ollama", name=f"m{index}")
            manager.join(source="ollama", name=f"m{index}", timeout=5)

    names = [state.name for state in manager.list()]
    assert len(names) == downloads.MAX_FINISHED_STATES
    assert names[-1] == f"m{downloads.MAX_FINISHED_STATES + 9}"


def test_whisper_download_failure_sets_italian_message(tmp_path: Path) -> None:
    def fake_snapshot(
        *, repo_id: str, allow_patterns: list[str], dry_run: bool = False, **_: object
    ) -> list[DryRunFileInfo] | str:
        if dry_run:
            return []
        raise OSError("disk full")

    with patch.object(downloads, "snapshot_download", side_effect=fake_snapshot):
        manager = downloads.DownloadManager(settings=Settings())
        manager.start(source="whisper", name="tiny")
        manager.join(source="whisper", name="tiny", timeout=5)
    state = manager.list()[0]
    assert state.status == "failed"
    assert state.message is not None
    assert "disk full" in state.message


def test_start_twice_same_model_conflicts(tmp_path: Path) -> None:
    hold = threading.Event()

    def fake_snapshot(
        *, repo_id: str, allow_patterns: list[str], dry_run: bool = False, **_: object
    ) -> list[DryRunFileInfo] | str:
        if dry_run:
            return []
        hold.wait(timeout=5)
        return str(tmp_path)

    with patch.object(downloads, "snapshot_download", side_effect=fake_snapshot):
        manager = downloads.DownloadManager(settings=Settings())
        manager.start(source="whisper", name="tiny")
        with pytest.raises(ConflictError):
            manager.start(source="whisper", name="tiny")
        hold.set()
        manager.join(source="whisper", name="tiny", timeout=5)


def test_ollama_download_sums_progress_across_digest_updates() -> None:
    step2 = threading.Event()
    step3 = threading.Event()

    def responses() -> object:
        yield ollama.ProgressResponse(
            status="pulling", completed=33, total=100, digest="sha256:a"
        )
        step2.wait(timeout=5)
        yield ollama.ProgressResponse(
            status="pulling", completed=66, total=100, digest="sha256:a"
        )
        step3.wait(timeout=5)
        yield ollama.ProgressResponse(
            status="success", completed=100, total=100, digest="sha256:a"
        )

    with patch.object(ollama, "Client") as factory:
        factory.return_value.__enter__.return_value.pull.return_value = responses()
        manager = downloads.DownloadManager(settings=Settings())
        manager.start(source="ollama", name="qwen3.5:9b")
        _wait_until(lambda: manager.list()[0].completed == 33)
        assert manager.list()[0].to_json()["fraction"] == pytest.approx(0.33)
        step2.set()
        _wait_until(lambda: manager.list()[0].completed == 66)
        assert manager.list()[0].to_json()["fraction"] == pytest.approx(0.66)
        step3.set()
        manager.join(source="ollama", name="qwen3.5:9b", timeout=5)
    state = manager.list()[0]
    assert state.status == "done"
    assert state.to_json()["fraction"] == 1.0


def test_ollama_download_unreachable_sets_italian_message() -> None:
    with patch.object(ollama, "Client") as factory:
        factory.return_value.__enter__.return_value.pull.side_effect = ConnectionError(
            "refused"
        )
        manager = downloads.DownloadManager(settings=Settings(ollama_host=HOST))
        manager.start(source="ollama", name="qwen3.5:9b")
        manager.join(source="ollama", name="qwen3.5:9b", timeout=5)
    state = manager.list()[0]
    assert state.status == "failed"
    assert state.message == "Ollama non è raggiungibile."

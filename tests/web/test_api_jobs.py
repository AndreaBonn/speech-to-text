import io
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import av
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sbobina.settings import Settings
from sbobina.web.api_jobs import source_name
from sbobina.web.app import create_app
from sbobina.web.job_models import (
    JobConfig,
    JobStatus,
    LectureMeta,
    StudyRun,
    StudyStatus,
)
from sbobina.web.job_store import JobStore
from sbobina.web.stage_runner import _find_audio

BASE_URL = "http://127.0.0.1:8765"
JOBS_URL = "/api/v1/jobs"
MIB = 1024 * 1024
WAV_HEADER_BYTES = 44


@pytest.fixture
def audio() -> bytes:
    buffer = io.BytesIO()
    with wave.open(f=buffer, mode="wb") as output:
        output.setnchannels(nchannels=1)
        output.setsampwidth(sampwidth=2)
        output.setframerate(framerate=8000)
        output.writeframes(data=b"\x00\x00" * 800)
    return buffer.getvalue()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(
        settings=Settings(web_max_upload_mb=1, beam_size=7), data_dir=tmp_path
    )
    app.state.supervisor.submit = Mock()
    # Without lifespan, no worker can start real transcription stages.
    transport = TestClient(app=app, base_url=BASE_URL, headers={"Origin": BASE_URL})
    yield transport
    transport.close()


def test_upload_valid_audio_creates_queued_job(
    client: TestClient, tmp_path: Path, audio: bytes
) -> None:
    response = client.post(
        url=JOBS_URL,
        files={"file": ("../../VOICE.WAV", audio, "audio/wav")},
        data={"subject": "Lezione", "correct": "true", "vad_filter": "true"},
    )

    assert response.status_code == 201
    record = response.json()["data"]
    cast(FastAPI, client.app).state.supervisor.submit.assert_called_once_with(
        job_id=record["id"]
    )
    assert record["status"] == "queued"
    assert record["config"]["beam_size"] == 7
    assert record["config"]["subject"] == "Lezione"
    assert record["config"]["correct"] is True
    assert record["config"]["vad_filter"] is True
    assert record["source_name"] == "VOICE.WAV"
    directory = tmp_path / "jobs" / record["id"]
    assert _find_audio(job_dir=directory) == directory / "audio.wav"
    assert (directory / "audio.wav").read_bytes() == audio
    assert sorted(path.name for path in directory.iterdir()) == [
        "audio.wav",
        "job.json",
    ]
    assert client.get(url=f"{JOBS_URL}/{record['id']}").json()["data"] == record


@pytest.mark.parametrize("filename", ["document.pdf", "fake.mp3", "empty.wav"])
def test_upload_invalid_file_returns_field_error_and_no_residue(
    client: TestClient, tmp_path: Path, filename: str
) -> None:
    response = client.post(
        url=JOBS_URL, files={"file": (filename, b"not audio", "audio/mpeg")}
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "file"
    assert list((tmp_path / "jobs").glob("*")) == []


def _video_only_mp4() -> bytes:
    buffer = io.BytesIO()
    with av.open(file=buffer, mode="w", format="mp4") as container:
        stream = container.add_stream(codec_name="mpeg4", rate=1)
        stream.width, stream.height, stream.pix_fmt = 16, 16, "yuv420p"
        frame = av.VideoFrame.from_ndarray(
            array=np.zeros(shape=(16, 16, 3), dtype=np.uint8), format="rgb24"
        )
        for packet in [*stream.encode(frame), *stream.encode()]:
            container.mux(packet)
    return buffer.getvalue()


def test_upload_container_without_audio_track_returns_field_error(
    client: TestClient, tmp_path: Path
) -> None:
    response = client.post(
        url=JOBS_URL, files={"file": ("video.m4a", _video_only_mp4(), "audio/mp4")}
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"] == [
        {"field": "file", "message": "Il file non contiene una traccia audio"}
    ]
    assert list((tmp_path / "jobs").glob("*")) == []


def test_upload_failing_to_queue_returns_500_and_removes_the_job(
    client: TestClient, tmp_path: Path, audio: bytes
) -> None:
    supervisor = cast(FastAPI, client.app).state.supervisor
    supervisor.submit.side_effect = OSError("disk full")

    response = client.post(
        url=JOBS_URL, files={"file": ("lezione.wav", audio, "audio/wav")}
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert list((tmp_path / "jobs").glob("*")) == []


@pytest.mark.parametrize("content_length", [str(2 * MIB), "0"])
def test_upload_over_limit_removes_attempt_directory(
    client: TestClient, tmp_path: Path, content_length: str
) -> None:
    response = client.post(
        url=JOBS_URL,
        files={"file": ("large.wav", b"x" * (2 * MIB), "audio/wav")},
        headers={"Content-Length": content_length},
    )

    assert response.status_code == 413
    assert response.json()["error"]["message"] == "Il file supera il limite consentito"
    assert list((tmp_path / "jobs").glob("*")) == []


def test_upload_invalid_config_returns_422_without_creating_job(
    client: TestClient, tmp_path: Path, audio: bytes
) -> None:
    response = client.post(
        url=JOBS_URL, files={"file": ("a.wav", audio)}, data={"beam_size": "0"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "body.beam_size"
    assert list((tmp_path / "jobs").glob("*")) == []


def test_list_jobs_pagination_returns_correct_meta(
    client: TestClient, tmp_path: Path
) -> None:
    store = JobStore(data_dir=tmp_path)
    records = [store.create(config=JobConfig()) for _ in range(3)]

    response = client.get(url=JOBS_URL, params={"page": 2, "per_page": 2})

    assert response.status_code == 200
    assert response.json()["meta"] == {
        "page": 2,
        "per_page": 2,
        "total": 3,
        "total_pages": 2,
        "status_counts": {"queued": 3},
    }
    assert [item["id"] for item in response.json()["data"]] == [str(records[0].id)]


def test_list_jobs_default_page_size_is_twenty(client: TestClient) -> None:
    response = client.get(url=JOBS_URL)

    assert response.status_code == 200
    assert response.json()["meta"]["per_page"] == 20


def test_list_jobs_zero_page_returns_validation_error(client: TestClient) -> None:
    response = client.get(url=JOBS_URL, params={"page": 0})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_get_job_missing_id_returns_404(client: TestClient) -> None:
    response = client.get(url=f"{JOBS_URL}/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_list_jobs_filters_effective_course(client: TestClient, tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    subjects = ["Diritto Privato", "Fisica", "Altro", None, "Diritto Privato"]
    records = [store.create(config=JobConfig(subject=subject)) for subject in subjects]
    store.write_meta(
        job_id=str(records[1].id), meta=LectureMeta(course="Diritto Privato")
    )
    store.write_meta(job_id=str(records[4].id), meta=LectureMeta(course="Fisica"))
    response = client.get(
        url=JOBS_URL, params={"course": "diritto privato", "per_page": 1}
    )
    assert response.status_code == 200
    assert response.json()["meta"] == {
        "page": 1,
        "per_page": 1,
        "total": 2,
        "total_pages": 2,
        "status_counts": {"queued": 2},
    }
    assert [item["id"] for item in response.json()["data"]] == [str(records[1].id)]
    missing = client.get(url=JOBS_URL, params={"course": ""}).json()
    assert [item["id"] for item in missing["data"]] == [str(records[3].id)]
    assert client.get(url=JOBS_URL).json()["meta"]["total"] == 5


def test_list_jobs_includes_effective_course(
    client: TestClient, tmp_path: Path
) -> None:
    """N4: the queue needs the course before it can show it in each card."""
    store = JobStore(data_dir=tmp_path)
    subject_only = store.create(config=JobConfig(subject="Fisica"))
    with_meta = store.create(config=JobConfig(subject="Fisica"))
    store.write_meta(job_id=str(with_meta.id), meta=LectureMeta(course="Diritto"))
    no_course = store.create(config=JobConfig())

    response = client.get(url=JOBS_URL)

    assert response.status_code == 200
    by_id = {item["id"]: item["course"] for item in response.json()["data"]}
    assert by_id[str(subject_only.id)] == "Fisica"
    assert by_id[str(with_meta.id)] == "Diritto"
    assert by_id[str(no_course.id)] is None


def test_get_job_includes_effective_course(client: TestClient, tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig(subject="Fisica"))

    response = client.get(url=f"{JOBS_URL}/{record.id}")

    assert response.status_code == 200
    assert response.json()["data"]["course"] == "Fisica"


def test_cancel_job_done_returns_conflict(client: TestClient, tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig())
    store.update(record=record.model_copy(update={"status": JobStatus.DONE}))

    response = client.post(url=f"{JOBS_URL}/{record.id}/cancel")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JOB_NOT_CANCELLABLE"


def test_cancel_job_queued_returns_cancelled(
    client: TestClient, tmp_path: Path
) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig())

    response = client.post(url=f"{JOBS_URL}/{record.id}/cancel")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "cancelled"
    assert store.get(job_id=str(record.id)).status == JobStatus.CANCELLED


@pytest.mark.parametrize("status", list(JobStatus))
def test_delete_job_protects_active_jobs_and_removes_terminal_jobs(
    client: TestClient, tmp_path: Path, status: JobStatus
) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig())
    store.update(record=record.model_copy(update={"status": status}))
    directory = store.jobs_dir / str(record.id)
    (directory / "audio.wav").write_bytes(data=b"audio")

    response = client.delete(url=f"{JOBS_URL}/{record.id}")

    active = status in (JobStatus.RUNNING, JobStatus.QUEUED)
    assert response.status_code == (409 if active else 204)
    assert directory.exists() == active


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("C:\\Users\\anna\\Lezione 3 - Diritto.m4a", "Lezione 3 - Diritto.m4a"),
        ("lezioni/2026/" + "a" * 300 + ".mp3", "a" * 196 + ".mp3"),
        ("lez\u202eione 3.m4a", "lezione 3.m4a"),
    ],
)
def test_upload_keeps_readable_source_name(
    client: TestClient, audio: bytes, filename: str, expected: str
) -> None:
    response = client.post(url=JOBS_URL, files={"file": (filename, audio, "audio/wav")})

    assert response.status_code == 201
    assert response.json()["data"]["source_name"] == expected


def test_source_name_drops_control_and_format_characters() -> None:
    # Browsers percent-encode newlines and NUL in multipart file names, so these
    # reach the function only through other clients: check it directly.
    assert source_name(filename="lez\u202eione\n3\x00\t.m4a") == "lezione3.m4a"


def _wav_of_exact_size(total_bytes: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(f=buffer, mode="wb") as output:
        output.setnchannels(nchannels=1)
        output.setsampwidth(sampwidth=2)
        output.setframerate(framerate=8000)
        output.writeframes(data=b"\x00\x00" * ((total_bytes - WAV_HEADER_BYTES) // 2))
    data = buffer.getvalue()
    assert len(data) == total_bytes
    return data


@pytest.mark.parametrize(("extra", "status"), [(0, 201), (2, 413)])
def test_upload_size_limit_is_inclusive(
    client: TestClient, extra: int, status: int
) -> None:
    audio = _wav_of_exact_size(total_bytes=MIB + extra)

    response = client.post(
        url=JOBS_URL, files={"file": ("limite.wav", audio, "audio/wav")}
    )

    assert response.status_code == status


@pytest.mark.parametrize("study_status", list(StudyStatus))
def test_delete_job_protects_an_active_study_on_a_done_job(
    client: TestClient, tmp_path: Path, study_status: StudyStatus
) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig())
    study = StudyRun(status=study_status, updated_at=record.updated_at)
    store.update(
        record=record.model_copy(update={"status": JobStatus.DONE, "study": study})
    )
    directory = store.jobs_dir / str(record.id)

    response = client.delete(url=f"{JOBS_URL}/{record.id}")

    active = study_status in (StudyStatus.QUEUED, StudyStatus.RUNNING)
    assert response.status_code == (409 if active else 204)
    assert directory.exists() == active


def _job_with_status(store: JobStore, status: JobStatus, subject: str) -> str:
    record = store.create(config=JobConfig(subject=subject))
    store.update(record=record.model_copy(update={"status": status}))
    return str(record.id)


def test_list_jobs_filters_by_status_and_counts_each_status(
    client: TestClient, tmp_path: Path
) -> None:
    """T1/C10: filter by one or more statuses; meta counts every status."""
    store = JobStore(data_dir=tmp_path)
    done = _job_with_status(store=store, status=JobStatus.DONE, subject="Diritto")
    _job_with_status(store=store, status=JobStatus.INTERRUPTED, subject="Diritto")
    _job_with_status(store=store, status=JobStatus.CANCELLED, subject="Diritto")
    _job_with_status(store=store, status=JobStatus.DONE, subject="Fisica")

    body = client.get(
        url=JOBS_URL, params={"course": "diritto", "status": "done"}
    ).json()

    assert [item["id"] for item in body["data"]] == [done]
    assert body["meta"]["total"] == 1
    assert body["meta"]["status_counts"] == {
        "done": 1,
        "interrupted": 1,
        "cancelled": 1,
    }


def test_list_jobs_accepts_several_statuses(client: TestClient, tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    _job_with_status(store=store, status=JobStatus.DONE, subject="Diritto")
    _job_with_status(store=store, status=JobStatus.INTERRUPTED, subject="Diritto")
    _job_with_status(store=store, status=JobStatus.CANCELLED, subject="Diritto")

    body = client.get(
        url=JOBS_URL, params=[("status", "interrupted"), ("status", "cancelled")]
    ).json()

    assert sorted(item["status"] for item in body["data"]) == [
        "cancelled",
        "interrupted",
    ]


def test_list_jobs_rejects_unknown_status(client: TestClient) -> None:
    response = client.get(url=JOBS_URL, params={"status": "sparita"})

    assert response.status_code == 422

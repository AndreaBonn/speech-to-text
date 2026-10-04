from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import cast
from urllib.parse import quote

import pytest
from conftest import make_segment, make_transcript, make_word
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sbobina.models import save_transcript
from sbobina.settings import Settings
from sbobina.web.api_files import transcript_revision
from sbobina.web.app import create_app
from sbobina.web.job_models import JobConfig
from sbobina.web.job_store import JobStore

BASE_URL = "http://127.0.0.1:8765"
ARTIFACTS = [
    ("md", "audio.md"),
    ("json", "audio.json"),
    ("corrected_md", "audio.corretto.md"),
    ("corrected_json", "audio.corretto.json"),
    ("report", "audio.correzioni.md"),
]
AUDIO = bytes(range(256)) * 8


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(
        settings=Settings(
            uncertain_threshold=0.1, paragraph_gap_s=0.5, paragraph_max_s=1.0
        ),
        data_dir=tmp_path,
    )
    transport = TestClient(app=app, base_url=BASE_URL)
    yield transport
    transport.close()


@pytest.fixture
def job_dir(client: TestClient) -> Path:
    store: JobStore = cast(FastAPI, client.app).state.job_store
    record = store.create(config=JobConfig(uncertain_threshold=0.7))
    directory = store.jobs_dir / str(record.id)
    (directory / "audio.wav").write_bytes(AUDIO)
    return directory


@pytest.mark.parametrize(
    ("kind", "filename", "download"),
    [
        ("md", "audio.md", "Lezione 3.md"),
        ("corrected_json", "audio.corretto.json", "Lezione 3.corretto.json"),
        ("report", "audio.correzioni.md", "Lezione 3.correzioni.md"),
    ],
)
def test_get_file_is_named_after_the_uploaded_audio(
    client: TestClient, kind: str, filename: str, download: str
) -> None:
    store: JobStore = cast(FastAPI, client.app).state.job_store
    record = store.create(config=JobConfig(), source_name="Lezione 3.m4a")
    (store.jobs_dir / str(record.id) / filename).write_text("x", encoding="utf-8")

    response = client.get(url=f"/api/v1/jobs/{record.id}/files/{kind}")

    assert response.status_code == 200
    # Starlette sends names with spaces in the RFC 5987 form.
    assert response.headers["content-disposition"] == (
        f"attachment; filename*=utf-8''{quote(download)}"
    )


def test_get_audio_range_returns_partial_content(
    client: TestClient, job_dir: Path
) -> None:
    response = client.get(
        url=f"/api/v1/jobs/{job_dir.name}/audio", headers={"Range": "bytes=0-1023"}
    )

    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 0-1023/{len(AUDIO)}"
    assert len(response.content) == 1024
    assert response.content == AUDIO[:1024]


@pytest.mark.parametrize(
    "extension,media_type",
    [
        ("wav", "audio/x-wav"),
        ("mp3", "audio/mpeg"),
        ("m4a", "audio/mp4"),
        ("ogg", "audio/ogg"),
        ("opus", "audio/ogg"),
        ("flac", "audio/flac"),
        ("webm", "audio/webm"),
        ("aac", "audio/aac"),
    ],
)
def test_get_audio_extension_returns_audio_type(
    client: TestClient, job_dir: Path, extension: str, media_type: str
) -> None:
    (job_dir / "audio.wav").rename(target=job_dir / f"audio.{extension}")

    response = client.get(url=f"/api/v1/jobs/{job_dir.name}/audio")

    assert response.status_code == 200
    assert response.headers["content-type"] == media_type
    assert response.content == AUDIO


def test_get_file_unknown_kind_returns_validation_envelope(
    client: TestClient, job_dir: Path
) -> None:
    response = client.get(url=f"/api/v1/jobs/{job_dir.name}/files/job.json")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("kind,filename", ARTIFACTS)
def test_get_file_produced_and_missing_returns_download_then_not_found(
    client: TestClient, job_dir: Path, kind: str, filename: str
) -> None:
    path = job_dir / filename
    path.write_text("contenuto", encoding="utf-8")
    url = f"/api/v1/jobs/{job_dir.name}/files/{kind}"

    response = client.get(url=url)
    path.unlink()
    missing = client.get(url=url)

    assert response.status_code == 200
    assert response.text == "contenuto"
    assert (
        response.headers["content-disposition"] == f'attachment; filename="{filename}"'
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "variant,filename",
    [("original", "audio.json"), ("corrected", "audio.corretto.json")],
)
def test_get_transcript_variant_returns_reader_then_not_found(
    client: TestClient, job_dir: Path, variant: str, filename: str
) -> None:
    word = replace(make_word(" cloroplasto", 0.0, 0.5), corrected_from="clorofilla")
    transcript = make_transcript(
        [make_segment([word]), make_segment([make_word(" dopo", 1.0)])]
    )
    save_transcript(transcript=transcript, path=job_dir / filename)
    url = f"/api/v1/jobs/{job_dir.name}/transcript?variant={variant}"

    response = client.get(url=url)
    revision = transcript_revision((job_dir / filename).read_text(encoding="utf-8"))
    (job_dir / filename).unlink()
    missing = client.get(url=url)

    assert response.status_code == 200
    assert response.json() == {
        "data": {
            "paragraphs": [
                [
                    {
                        "index": 0,
                        "segment": 0,
                        "start": 0.0,
                        "end": 0.4,
                        "text": " cloroplasto",
                        "uncertain": True,
                        "corrected_from": "clorofilla",
                    }
                ],
                [
                    {
                        "index": 1,
                        "segment": 1,
                        "start": 1.0,
                        "end": 1.4,
                        "text": " dopo",
                        "uncertain": False,
                        "corrected_from": None,
                    }
                ],
            ],
            "review_points": [
                {"start": 0.0, "before": "", "text": "cloroplasto", "after": "dopo"}
            ],
        },
        "meta": {"revision": revision},
    }
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


def test_get_transcript_invalid_variant_returns_validation_envelope(
    client: TestClient, job_dir: Path
) -> None:
    response = client.get(url=f"/api/v1/jobs/{job_dir.name}/transcript?variant=other")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("endpoint", ["audio", "files/md", "transcript"])
@pytest.mark.parametrize(
    "job_id", ["not-a-uuid", "00000000-0000-4000-8000-000000000000"]
)
def test_get_resource_unknown_job_returns_not_found(
    client: TestClient, endpoint: str, job_id: str
) -> None:
    response = client.get(url=f"/api/v1/jobs/{job_id}/{endpoint}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_get_audio_uuid_alias_resolves_canonical_directory(
    client: TestClient, job_dir: Path
) -> None:
    response = client.get(url=f"/api/v1/jobs/{job_dir.name.upper()}/audio")

    assert response.status_code == 200
    assert response.content == AUDIO


def test_get_audio_when_recording_was_removed_returns_not_found(
    client: TestClient, job_dir: Path
) -> None:
    (job_dir / "audio.wav").unlink()

    response = client.get(url=f"/api/v1/jobs/{job_dir.name}/audio")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"

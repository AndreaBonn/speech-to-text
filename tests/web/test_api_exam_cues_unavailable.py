import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import make_segment, make_transcript, make_word
from fastapi.testclient import TestClient

from sbobina.models import save_transcript
from sbobina.settings import Settings
from sbobina.web import api_exam_cues
from sbobina.web.api_files import TRANSCRIPT_FILES
from sbobina.web.app import create_app
from sbobina.web.job_models import JobConfig
from sbobina.web.job_store import JobStore

URL = "/api/v1/courses/diritto/exam-cues"
BASE_URL = "http://127.0.0.1:8765"


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(data_dir=tmp_path)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    transport = TestClient(app=app, base_url=BASE_URL)
    yield transport
    transport.close()


def _write_transcript(path: Path, text: str) -> None:
    transcript = make_transcript(
        segments=[make_segment(words=[make_word(text=text, start=12.5)])]
    )
    save_transcript(transcript=transcript, path=path)


def _lecture(store: JobStore, text: str, subject: str = "Diritto") -> str:
    job_id = str(store.create(config=JobConfig(subject=subject)).id)
    _write_transcript(
        path=store.jobs_dir / job_id / TRANSCRIPT_FILES["original"], text=text
    )
    return job_id


def test_list_exam_cues_all_readable_reports_no_unavailable_jobs(
    client: TestClient, store: JobStore
) -> None:
    _lecture(store=store, text="Segnatevelo")

    response = client.get(url=URL)

    assert response.status_code == 200
    assert response.json()["meta"]["unavailable_jobs"] == []


def test_list_exam_cues_detector_type_error_is_not_swallowed(
    client: TestClient, store: JobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A logic bug in the detector must surface, unlike corrupted data on disk
    # (see test_list_exam_cues_wrong_field_type_marks_job_unavailable).
    _lecture(store=store, text="Segnatevelo")

    def broken_detector(transcript: object, job_id: str) -> None:
        raise TypeError("detector bug")

    monkeypatch.setattr(
        target=api_exam_cues, name="find_exam_cues", value=broken_detector
    )

    with pytest.raises(TypeError, match="detector bug"):
        client.get(url=URL)


def test_list_exam_cues_wrong_field_type_marks_job_unavailable(
    client: TestClient, store: JobStore
) -> None:
    good = _lecture(store=store, text="Segnatevelo")
    bad = _lecture(store=store, text="Ricordatevi il termine")
    path = store.jobs_dir / bad / TRANSCRIPT_FILES["original"]
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["segments"][0]["words"][0]["text"] = None
    path.write_text(json.dumps(raw), encoding="utf-8")

    response = client.get(url=URL)

    assert response.status_code == 200
    assert [cue["job_id"] for cue in response.json()["data"]] == [good]
    assert response.json()["meta"]["unavailable_jobs"] == [bad]

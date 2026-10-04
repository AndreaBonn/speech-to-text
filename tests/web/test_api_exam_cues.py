import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import make_segment, make_transcript, make_word
from fastapi.testclient import TestClient

from sbobina.course_registry import get_or_create
from sbobina.models import save_transcript
from sbobina.settings import Settings
from sbobina.web.api_files import TRANSCRIPT_FILES
from sbobina.web.app import create_app
from sbobina.web.course_retrieval import lecture_revision
from sbobina.web.job_models import JobConfig, LectureMeta
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
        segments=[
            make_segment(
                words=[
                    make_word(text=text, start=12.5),
                ]
            )
        ]
    )
    save_transcript(transcript=transcript, path=path)


def _lecture(store: JobStore, text: str, subject: str = "Diritto") -> str:
    job_id = str(store.create(config=JobConfig(subject=subject)).id)
    _write_transcript(
        path=store.jobs_dir / job_id / TRANSCRIPT_FILES["original"], text=text
    )
    return job_id


def test_list_exam_cues_envelope_and_reader_link(
    client: TestClient, store: JobStore
) -> None:
    job_id = _lecture(store=store, text="Introduzione. Segnatevelo")
    revision = lecture_revision(store=store, job_id=job_id)

    response = client.get(url=URL)

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "job_id": job_id,
                "segment_index": 0,
                "quote": "Segnatevelo",
                "start": 12.5,
                "level": "strong",
                "href": f"/lettore/{job_id}?t=12.5&variant=original",
                "revision": revision,
            }
        ],
        "meta": {"page": 1, "per_page": 20, "total": 1, "total_pages": 1},
    }
    assert revision is not None


def test_list_exam_cues_strong_filters_before_pagination(
    client: TestClient, store: JobStore
) -> None:
    _lecture(store=store, text="Importante. Segnatevelo. Fondamentale. Lo chiedo")
    all_cues = client.get(url=URL, params={"level": "all"}).json()

    response = client.get(url=URL, params={"level": "strong", "page": 2, "per_page": 1})

    assert len(all_cues["data"]) == 4
    assert response.status_code == 200
    assert [cue["quote"] for cue in response.json()["data"]] == ["Lo chiedo"]
    assert response.json()["meta"] == {
        "page": 2,
        "per_page": 1,
        "total": 2,
        "total_pages": 2,
    }


@pytest.mark.parametrize("level", ["x", "weak", ""])
def test_list_exam_cues_invalid_level_returns_422(
    client: TestClient, level: str
) -> None:
    response = client.get(url=URL, params={"level": level})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "params", [{"page": "0"}, {"per_page": "0"}, {"page": "x"}, {"per_page": "-1"}]
)
def test_list_exam_cues_invalid_pagination_returns_field_details(
    client: TestClient, params: dict[str, str]
) -> None:
    response = client.get(url=URL, params=params)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"][0]["field"] == f"query.{next(iter(params))}"


def test_list_exam_cues_unknown_course_returns_404(client: TestClient) -> None:
    response = client.get(url=URL)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_list_exam_cues_registered_empty_course_returns_200(
    client: TestClient, store: JobStore
) -> None:
    get_or_create(courses_dir=store.courses_dir, key="diritto", label="Diritto")
    assert client.get(url=URL).json() == {
        "data": [],
        "meta": {"page": 1, "per_page": 20, "total": 0, "total_pages": 0},
    }
    assert client.get(url=URL).status_code == 200
    _lecture(store=store, text="Segnatevelo")
    assert len(client.get(url=URL).json()["data"]) == 1


def test_list_exam_cues_lecture_without_signals_returns_200(
    client: TestClient, store: JobStore
) -> None:
    _lecture(store=store, text="l'importante è che abbiate capito")
    response = client.get(url=URL)
    assert response.status_code == 200
    assert response.json()["data"] == []
    _lecture(store=store, text="Segnatevelo")
    assert len(client.get(url=URL).json()["data"]) == 1


def test_list_exam_cues_scope_uses_effective_course(
    client: TestClient, store: JobStore
) -> None:
    included = _lecture(store=store, text="Segnatevelo", subject="Fisica")
    _lecture(store=store, text="Lo chiedo", subject="Fisica")
    store.write_meta(job_id=included, meta=LectureMeta(course="Diritto"))
    assert [cue["job_id"] for cue in client.get(url=URL).json()["data"]] == [included]


def test_list_exam_cues_corrected_transcript_replaces_original(
    client: TestClient, store: JobStore
) -> None:
    job_id = _lecture(store=store, text="Segnatevelo")
    assert client.get(url=URL).json()["data"][0]["quote"] == "Segnatevelo"
    corrected = store.jobs_dir / job_id / TRANSCRIPT_FILES["corrected"]
    _write_transcript(path=corrected, text="Questo è importante")
    corrected_cues = client.get(url=URL).json()["data"]
    assert [cue["quote"] for cue in corrected_cues] == ["Questo è importante"]
    assert corrected_cues[0]["href"] == f"/lettore/{job_id}?t=12.5&variant=corrected"
    _write_transcript(path=corrected, text="Nessun segnale")
    assert client.get(url=URL).json()["data"] == []


@pytest.mark.parametrize(
    "content",
    [
        "{",
        "{}",
        '{"segments": null}',
        None,
        json.dumps(
            {
                "source": "lecture",
                "model": "test",
                "language": "it",
                "duration": 20,
                "segments": [
                    {
                        "start": -1,
                        "end": 20,
                        "words": [
                            {
                                "start": -1,
                                "end": 20,
                                "text": "Segnatevelo",
                                "probability": 1,
                            },
                        ],
                    }
                ],
            }
        ),
        json.dumps(
            {
                "source": "lecture",
                "model": "test",
                "language": "it",
                "duration": 20,
                "segments": [
                    {
                        "start": 0,
                        "end": 20,
                        "words": [
                            {"start": 0, "end": 20, "text": None, "probability": 1},
                        ],
                    }
                ],
            }
        ),
    ],
)
def test_list_exam_cues_unreadable_corrected_skips_lecture(
    client: TestClient,
    store: JobStore,
    caplog: pytest.LogCaptureFixture,
    content: str | None,
) -> None:
    good = _lecture(store=store, text="Segnatevelo")
    bad = _lecture(store=store, text="Ricordatevi il termine")
    corrected = store.jobs_dir / bad / TRANSCRIPT_FILES["corrected"]
    if content is None:
        corrected.mkdir()
    else:
        corrected.write_text(data=content, encoding="utf-8")

    with caplog.at_level(level=logging.WARNING):
        response = client.get(url=URL)

    assert response.status_code == 200
    assert [cue["job_id"] for cue in response.json()["data"]] == [good]
    assert str(corrected) in caplog.text


def test_list_exam_cues_missing_transcript_skips_lecture(
    client: TestClient, store: JobStore
) -> None:
    good = _lecture(store=store, text="Segnatevelo")
    store.create(config=JobConfig(subject="Diritto"))
    assert [cue["job_id"] for cue in client.get(url=URL).json()["data"]] == [good]


def test_list_exam_cues_pages_follow_job_and_sentence_order(
    client: TestClient, store: JobStore
) -> None:
    jobs = sorted(
        _lecture(store=store, text="Importante. Segnatevelo") for _ in range(2)
    )
    pages = [
        client.get(url=URL, params={"page": page, "per_page": 1}).json()
        for page in range(1, 6)
    ]
    assert [
        (body["data"][0]["job_id"], body["data"][0]["quote"]) for body in pages[:4]
    ] == [(job_id, quote) for job_id in jobs for quote in ("Importante", "Segnatevelo")]
    assert pages[4] == {
        "data": [],
        "meta": {"page": 5, "per_page": 1, "total": 4, "total_pages": 4},
    }


def test_list_exam_cues_path_course_key(client: TestClient, store: JobStore) -> None:
    job_id = _lecture(store=store, text="Segnatevelo", subject="Diritto/privato")
    response = client.get(url="/api/v1/courses/diritto/privato/exam-cues")
    assert response.status_code == 200
    assert response.json()["data"][0]["job_id"] == job_id

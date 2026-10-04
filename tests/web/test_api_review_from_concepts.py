"""POST /jobs/{id}/cards/from-concepts: import, dedup and concurrency (card_store)."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import make_segment, make_transcript, make_word
from fastapi.testclient import TestClient
from test_concept_cards import study_fixture

from sbobina.card_models import LectureAnchor
from sbobina.course_registry import find_by_key
from sbobina.models import save_transcript
from sbobina.settings import Settings
from sbobina.study_render import STUDY_ADAPTER
from sbobina.web.app import create_app
from sbobina.web.card_store import load_cards
from sbobina.web.course_retrieval import lecture_revision
from sbobina.web.job_models import JobConfig, LectureMeta
from sbobina.web.job_store import JobStore

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


def _material(store: JobStore, subject: str | None = "Diritto") -> str:
    job_id = str(store.create(config=JobConfig(subject=subject)).id)
    result = study_fixture()
    chapter = result.chapters[0]
    concepts = tuple(
        replace(item, citations=item.citations[:1]) for item in chapter.concepts
    )
    result = replace(result, chapters=(replace(chapter, concepts=concepts),))
    transcript = make_transcript(
        segments=[
            make_segment(
                words=[make_word(text=item.citations[0].quote, start=float(i))]
            )
            for i, item in enumerate(result.chapters[0].concepts)
        ]
    )
    directory = store.jobs_dir / job_id
    save_transcript(transcript=transcript, path=directory / "audio.json")
    (directory / "audio.studio.json").write_text(
        data=STUDY_ADAPTER.dump_json(result).decode("utf-8"), encoding="utf-8"
    )
    return job_id


def _concept_url(job_id: str) -> str:
    return f"/api/v1/jobs/{job_id}/cards/from-concepts"


def test_from_concepts_twelve_then_zero_with_effective_course(
    client: TestClient, store: JobStore
) -> None:
    job_id = _material(store=store, subject="Fisica")
    store.write_meta(job_id=job_id, meta=LectureMeta(course="Diritto"))
    response = client.post(url=_concept_url(job_id=job_id))
    assert response.status_code == 201 and response.json() == {"data": {"created": 12}}
    assert client.post(url=_concept_url(job_id=job_id)).json() == {
        "data": {"created": 0}
    }
    course = find_by_key(courses_dir=store.courses_dir, key="diritto")
    assert course is not None
    cards = load_cards(courses_dir=store.courses_dir, course_id=course.id)
    assert len(cards) == 12
    assert cards[0].front == "concetto0" and cards[0].back == "Spiegazione 0"
    assert isinstance(cards[0].anchor, LectureAnchor)
    assert cards[0].anchor.revision == lecture_revision(store=store, job_id=job_id)


def test_from_concepts_missing_study_and_uncategorized_errors(
    client: TestClient, store: JobStore
) -> None:
    job_id = _material(store=store, subject=None)
    response = client.post(url=_concept_url(job_id=job_id))
    assert (
        response.status_code == 409
        and response.json()["error"]["code"] == "COURSE_REQUIRED"
    )
    store.write_meta(job_id=job_id, meta=LectureMeta(course="Diritto"))
    assert client.post(url=_concept_url(job_id=job_id)).status_code == 201
    (store.jobs_dir / job_id / "audio.studio.json").unlink()
    response = client.post(url=_concept_url(job_id=job_id))
    assert (
        response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"
    )


def test_from_concepts_concurrent_import_counts_only_own_creations(
    client: TestClient, store: JobStore
) -> None:
    url = _concept_url(job_id=_material(store=store))
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: client.post(url=url), range(2)))
    assert [response.status_code for response in responses] == [201, 201]
    assert sorted(response.json()["data"]["created"] for response in responses) == [
        0,
        12,
    ]

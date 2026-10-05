from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from package_round_trip_fixtures import (
    CARD_COUNT,
    LABEL,
    LECTURE_COUNT,
    SourceCourse,
    document_text,
    seed_round_trip_course,
)

from sbobina.document_models import CourseDocument
from sbobina.generation_models import GenerationFormat
from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.document_store import iter_documents
from sbobina.web.generation_store import iter_generations

PORT = 8765
BASE_URL = f"http://127.0.0.1:{PORT}"
TRANSCRIPT_FILES = ("audio.json", "audio.corretto.json")


@pytest.fixture
def source(tmp_path: Path) -> SourceCourse:
    return seed_round_trip_course(data_dir=tmp_path / "source")


def make_client(data_dir: Path) -> TestClient:
    app = create_app(settings=Settings(web_port=PORT), data_dir=data_dir)
    return TestClient(app=app, base_url=BASE_URL, headers={"Origin": BASE_URL})


@pytest.fixture
def target(tmp_path: Path) -> Iterator[TestClient]:
    with make_client(data_dir=tmp_path / "target") as client:
        yield client


def exported_package(source: SourceCourse) -> bytes:
    with make_client(data_dir=source.data_dir) as client:
        response: Response = client.get(url="/api/v1/courses/fisica/export")
    assert response.status_code == 200
    return response.content


def import_package(client: TestClient, package: bytes) -> dict[str, Any]:
    response = client.post(
        url="/api/v1/courses/import",
        files={"file": ("fisica.sbobina.zip", package, "application/zip")},
    )
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


def course_key(client: TestClient, label: str) -> str:
    courses = client.get(url="/api/v1/courses").json()["data"]
    return str(next(course["key"] for course in courses if course["label"] == label))


def listed(client: TestClient, url: str) -> list[dict[str, Any]]:
    response = client.get(url=url, params={"per_page": 100})
    assert response.status_code == 200, response.text
    data: list[dict[str, Any]] = response.json()["data"]
    return data


def generation_citations(client: TestClient, key: str) -> list[dict[str, Any]]:
    found = []
    for item in listed(client=client, url=f"/api/v1/courses/{key}/generations"):
        detail = client.get(url=f"/api/v1/courses/{key}/generations/{item['id']}")
        data = detail.json()["data"]
        for question in data["questions"]:
            found += question["citations"]
        for section in data["sections"]:
            for sentence in section["sentences"]:
                found += sentence["citations"]
    return found


@dataclass(frozen=True)
class ImportedCourse:
    key: str
    data_dir: Path
    job_ids: frozenset[str]
    documents: tuple[CourseDocument, ...]


@pytest.fixture
def imported(
    source: SourceCourse, target: TestClient, tmp_path: Path
) -> ImportedCourse:
    data = import_package(client=target, package=exported_package(source=source))
    data_dir = tmp_path / "target"
    job_ids = frozenset(job["id"] for job in listed(client=target, url="/api/v1/jobs"))
    assert len(job_ids) == LECTURE_COUNT
    return ImportedCourse(
        key=course_key(client=target, label=LABEL),
        data_dir=data_dir,
        job_ids=job_ids,
        documents=tuple(
            iter_documents(
                courses_dir=data_dir / "courses", course_id=data["course_id"]
            )
        ),
    )


def test_round_trip_keeps_counts_with_new_ids(
    source: SourceCourse, target: TestClient, imported: ImportedCourse
) -> None:
    key = imported.key
    generations = listed(client=target, url=f"/api/v1/courses/{key}/generations")
    cards = listed(client=target, url=f"/api/v1/courses/{key}/cards")

    assert not imported.job_ids & set(source.job_ids)
    assert [document.filename for document in imported.documents] == ["Notes.txt"]
    assert imported.documents[0].id != source.doc_id
    assert sorted(item["format"] for item in generations) == sorted(GenerationFormat)
    assert len(cards) == CARD_COUNT


def test_round_trip_keeps_lecture_and_document_text(
    source: SourceCourse, imported: ImportedCourse
) -> None:
    source_job = source.store.jobs_dir / source.job_ids[0]
    source_document = next(
        iter_documents(courses_dir=source.store.courses_dir, course_id=source.course.id)
    )

    for job_id in imported.job_ids:
        for name in TRANSCRIPT_FILES:
            copied = (imported.data_dir / "jobs" / job_id / name).read_bytes()
            assert copied == (source_job / name).read_bytes()
    assert document_text(
        courses_dir=imported.data_dir / "courses", document=imported.documents[0]
    ) == document_text(courses_dir=source.store.courses_dir, document=source_document)


def test_round_trip_generation_sources_point_to_the_new_course(
    imported: ImportedCourse,
) -> None:
    doc_id = imported.documents[0].id
    for _, record in iter_generations(courses_dir=imported.data_dir / "courses"):
        assert {source.doc_id for source in record.sources} == {doc_id, None}
        assert {source.job_id for source in record.sources} == {*imported.job_ids, None}
        assert record.requested_sources.doc_ids == (doc_id,)
        assert set(record.requested_sources.job_ids) == imported.job_ids


def test_round_trip_citations_open_reader_and_document_page(
    target: TestClient, imported: ImportedCourse
) -> None:
    key = imported.key
    citations = generation_citations(client=target, key=key)
    cards = listed(client=target, url=f"/api/v1/courses/{key}/cards")

    paths = {urlsplit(citation["href"]).path for citation in citations}
    assert paths == {f"/lettore/{job_id}" for job_id in imported.job_ids} | {
        f"/corsi/{key}/documenti/{imported.documents[0].id}"
    }
    for path in paths:
        assert target.get(url=path).status_code == 200, path
    assert {card["anchor_resolution"]["status"] for card in cards} == {"ok"}
    # Generation anchors point to a page that does not exist yet (F51).
    anchored = {
        urlsplit(card["anchor_resolution"]["href"]).path
        for card in cards
        if card["anchor"]["kind"] != "generation"
    }
    assert anchored == paths


def test_round_trip_is_searchable_without_restart(
    target: TestClient, imported: ImportedCourse
) -> None:
    lectures = target.get(url="/api/v1/search", params={"q": "contratto"}).json()
    documents = target.get(url="/api/v1/search", params={"q": "notes"}).json()

    hits = {item["id"] for item in lectures["data"] if "passages" in item}
    assert hits == imported.job_ids
    assert [item["kind"] for item in documents["data"]] == ["document"]


def test_round_trip_twice_makes_a_second_course_with_suffix(
    source: SourceCourse, target: TestClient
) -> None:
    package = exported_package(source=source)

    first = import_package(client=target, package=package)
    second = import_package(client=target, package=package)

    labels = sorted(
        course["label"] for course in listed(client=target, url="/api/v1/courses")
    )
    assert first["warning"] is None
    assert second["warning"] is not None
    assert second["warning"].startswith("già importato il ")
    assert labels[0] == LABEL
    assert labels[1].startswith(f"{LABEL} (importato ")
    assert len(listed(client=target, url="/api/v1/jobs")) == 2 * LECTURE_COUNT

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sbobina.course_registry import get_or_create
from sbobina.document_models import CourseDocument, DocumentKind, DocumentStatus
from sbobina.extracted_text import ExtractedText, Page
from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.document_store import read_document, write_document, write_text
from sbobina.web.errors import NotFoundError

BASE_URL = "http://127.0.0.1:8765"
SEARCH_URL = "/api/v1/search"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    transport = TestClient(app=app, base_url=BASE_URL, headers={"Origin": BASE_URL})
    yield transport
    transport.close()


def write_ready_document(
    courses_dir: Path, course_id: str, doc_id: str, filename: str, pages: list[str]
) -> None:
    doc_dir = courses_dir / course_id / "documents" / doc_id
    doc_dir.mkdir(parents=True)
    write_document(
        courses_dir=courses_dir,
        document=CourseDocument(
            id=doc_id,
            course_id=course_id,
            filename=filename,
            kind=DocumentKind.PDF,
            size=10,
            sha256="0" * 64,
            status=DocumentStatus.READY,
            error=None,
            pages=len(pages),
            created_at=datetime.now(tz=UTC),
        ),
    )
    write_text(
        doc_dir=doc_dir,
        extracted=ExtractedText(
            pages=tuple(Page(text=text, no_text=False) for text in pages),
            status=DocumentStatus.READY,
        ),
    )


def test_search_finds_document_passage_with_course_filter_and_href(
    client: TestClient, tmp_path: Path
) -> None:
    courses_dir = tmp_path / "courses"
    course = get_or_create(
        courses_dir=courses_dir, key="diritto privato", label="Diritto privato"
    )
    pages = ["testo di riempimento"] * 213 + ["la causa del contratto è illecita"]
    write_ready_document(
        courses_dir=courses_dir,
        course_id=course.id,
        doc_id="doc-214",
        filename="manuale.pdf",
        pages=pages,
    )

    response = client.get(
        url=SEARCH_URL,
        params={"q": "causa illecita", "course": "diritto privato"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == [
        {
            "kind": "document",
            "doc_id": "doc-214",
            "filename": "manuale.pdf",
            "course": "Diritto privato",
            "page": 214,
            "snippet": [
                {"text": "la ", "match": False},
                {"text": "causa", "match": True},
                {"text": " del contratto è ", "match": False},
                {"text": "illecita", "match": True},
            ],
            "href": "/corsi/diritto%20privato/documenti/doc-214?p=214&q=causa%20illecita",
        }
    ]
    # Pagination describes lectures; documents_total says how many document
    # passages matched, of which at most SEARCH_DOCUMENT_RESULTS_LIMIT are shown.
    assert body["meta"] == {
        "page": 1,
        "per_page": 20,
        "total": 0,
        "total_pages": 0,
        "documents_total": 1,
    }


def test_search_document_respects_course_filter(
    client: TestClient, tmp_path: Path
) -> None:
    courses_dir = tmp_path / "courses"
    course = get_or_create(courses_dir=courses_dir, key="fisica", label="Fisica")
    write_ready_document(
        courses_dir=courses_dir,
        course_id=course.id,
        doc_id="doc-1",
        filename="appunti.pdf",
        pages=["la causa del moto"],
    )

    response = client.get(
        url=SEARCH_URL, params={"q": "causa", "course": "diritto privato"}
    )

    assert response.status_code == 200
    assert response.json()["data"] == []


def test_search_omits_documents_of_an_unregistered_course(
    client: TestClient, tmp_path: Path
) -> None:
    courses_dir = tmp_path / "courses"
    course = get_or_create(courses_dir=courses_dir, key="fisica", label="Fisica")
    write_ready_document(
        courses_dir=courses_dir,
        course_id=course.id,
        doc_id="registrato",
        filename="appunti.pdf",
        pages=["la causa del moto"],
    )
    write_ready_document(
        courses_dir=courses_dir,
        course_id="corso-senza-registro",
        doc_id="orfano",
        filename="orfano.pdf",
        pages=["la causa del moto"],
    )

    response = client.get(url=SEARCH_URL, params={"q": "causa"})

    assert [hit["doc_id"] for hit in response.json()["data"]] == ["registrato"]


def test_search_omits_a_document_deleted_after_the_index_query(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    courses_dir = tmp_path / "courses"
    course = get_or_create(courses_dir=courses_dir, key="fisica", label="Fisica")
    for doc_id in ("rimasto", "cancellato"):
        write_ready_document(
            courses_dir=courses_dir,
            course_id=course.id,
            doc_id=doc_id,
            filename=f"{doc_id}.pdf",
            pages=["la causa del moto"],
        )

    def read_racing_a_delete(
        courses_dir: Path, course_id: str, doc_id: str
    ) -> CourseDocument:
        if doc_id == "cancellato":
            raise NotFoundError(entity="Documento", id=doc_id)
        return read_document(
            courses_dir=courses_dir, course_id=course_id, doc_id=doc_id
        )

    monkeypatch.setattr("sbobina.web.api_search.read_document", read_racing_a_delete)

    response = client.get(url=SEARCH_URL, params={"q": "causa"})

    assert response.status_code == 200
    assert [hit["doc_id"] for hit in response.json()["data"]] == ["rimasto"]

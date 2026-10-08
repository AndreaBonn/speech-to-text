from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from ocr_fixtures import COURSE_KEY, DOC_ID, add_scanned_document

from sbobina.document_models import DocumentStatus
from sbobina.extracted_text import ExtractedText, Page
from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.document_store import write_text

BASE_URL = "http://127.0.0.1:8765"
DOC_URL = f"/api/v1/courses/{COURSE_KEY}/documents/{DOC_ID}"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    transport = TestClient(app=app, base_url=BASE_URL, headers={"Origin": BASE_URL})
    yield transport
    transport.close()


def test_start_ocr_queues_it_and_status_reads_back(
    client: TestClient, tmp_path: Path
) -> None:
    add_scanned_document(courses_dir=tmp_path / "courses")

    started = client.post(f"{DOC_URL}/ocr")
    status = client.get(f"{DOC_URL}/ocr")

    assert started.status_code == 202
    assert started.json()["data"]["status"] == "queued"
    # No lifespan in this client: the supervisor never starts, so the run stays queued.
    assert status.json()["data"]["status"] == "queued"


def test_start_ocr_twice_returns_already_queued(
    client: TestClient, tmp_path: Path
) -> None:
    add_scanned_document(courses_dir=tmp_path / "courses")
    client.post(f"{DOC_URL}/ocr")

    again = client.post(f"{DOC_URL}/ocr")

    assert again.status_code == 409
    assert again.json()["error"]["code"] == "OCR_ALREADY_QUEUED"


def test_start_ocr_document_with_text_returns_not_eligible(
    client: TestClient, tmp_path: Path
) -> None:
    _, doc_dir = add_scanned_document(
        courses_dir=tmp_path / "courses", status=DocumentStatus.READY
    )
    write_text(
        doc_dir=doc_dir,
        extracted=ExtractedText(
            pages=(Page(text="Testo nativo", no_text=False),),
            status=DocumentStatus.READY,
        ),
    )

    response = client.post(f"{DOC_URL}/ocr")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OCR_NOT_ELIGIBLE"


def test_ocr_status_without_a_run_is_not_found(
    client: TestClient, tmp_path: Path
) -> None:
    add_scanned_document(courses_dir=tmp_path / "courses")

    assert client.get(f"{DOC_URL}/ocr").status_code == 404


def test_cancel_ocr_marks_it_interrupted(client: TestClient, tmp_path: Path) -> None:
    add_scanned_document(courses_dir=tmp_path / "courses")
    client.post(f"{DOC_URL}/ocr")

    cancelled = client.post(f"{DOC_URL}/ocr/cancel")

    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "interrupted"


def test_delete_is_refused_while_ocr_is_pending(
    client: TestClient, tmp_path: Path
) -> None:
    add_scanned_document(courses_dir=tmp_path / "courses")
    client.post(f"{DOC_URL}/ocr")

    response = client.delete(DOC_URL)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OCR_IN_PROGRESS"


def test_foreign_origin_cannot_start_ocr(client: TestClient, tmp_path: Path) -> None:
    add_scanned_document(courses_dir=tmp_path / "courses")

    response = client.post(f"{DOC_URL}/ocr", headers={"Origin": "http://evil.example"})

    assert response.status_code == 403


def test_page_says_when_its_text_came_from_ocr(
    client: TestClient, tmp_path: Path
) -> None:
    _, doc_dir = add_scanned_document(
        courses_dir=tmp_path / "courses", status=DocumentStatus.READY
    )
    write_text(
        doc_dir=doc_dir,
        extracted=ExtractedText(
            pages=(
                Page(text="testo letto", no_text=False, ocr=True),
                Page(text="testo nativo", no_text=False),
            ),
            status=DocumentStatus.READY,
        ),
    )

    first = client.get(f"{DOC_URL}/pages/1").json()["data"]
    second = client.get(f"{DOC_URL}/pages/2").json()["data"]

    assert first["ocr"] is True
    assert second["ocr"] is False


def test_page_past_the_last_one_is_not_found(
    client: TestClient, tmp_path: Path
) -> None:
    add_scanned_document(courses_dir=tmp_path / "courses", status=DocumentStatus.READY)

    last = client.get(f"{DOC_URL}/pages/2")
    past = client.get(f"{DOC_URL}/pages/3")

    assert (last.status_code, past.status_code) == (200, 404)

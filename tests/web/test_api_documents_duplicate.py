"""Duplicate upload within a course is rejected (A7, adr.md D5)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.document_store import mark_failed

BASE_URL = "http://127.0.0.1:8765"
COURSES_URL = "/api/v1/courses"
PDF_BYTES = b"%PDF-1.4\n%%EOF"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    transport = TestClient(app=app, base_url=BASE_URL, headers={"Origin": BASE_URL})
    yield transport
    transport.close()


def upload(client: TestClient, key: str, filename: str, content: bytes) -> Any:
    return client.post(
        f"{COURSES_URL}/{key}/documents",
        files={"file": (filename, content, "application/octet-stream")},
    )


def test_duplicate_upload_in_same_course_is_conflict(
    client: TestClient, tmp_path: Path
) -> None:
    first = upload(client, "fisica", "manuale.pdf", PDF_BYTES)
    assert first.status_code == 202

    second = upload(client, "fisica", "copia.pdf", PDF_BYTES)

    assert second.status_code == 409
    body = second.json()["error"]
    assert body["code"] == "DOCUMENT_EXISTS"
    assert "manuale.pdf" in body["message"]
    listed = client.get(f"{COURSES_URL}/fisica/documents").json()["data"]
    assert len(listed) == 1
    assert list((tmp_path / "courses").glob("*/documents/*")) == [
        (tmp_path / "courses" / listed[0]["course_id"] / "documents" / listed[0]["id"])
    ]


def test_same_file_in_a_different_course_is_accepted(client: TestClient) -> None:
    upload(client, "fisica", "manuale.pdf", PDF_BYTES)

    response = upload(client, "chimica", "manuale.pdf", PDF_BYTES)

    assert response.status_code == 202


def test_reupload_after_failed_document_is_accepted(
    client: TestClient, tmp_path: Path
) -> None:
    uploaded = upload(client, "fisica", "manuale.pdf", PDF_BYTES).json()["data"]
    mark_failed(
        courses_dir=tmp_path / "courses",
        course_id=uploaded["course_id"],
        doc_id=uploaded["id"],
        code="EXTRACTION_FAILED",
    )

    response = upload(client, "fisica", "manuale.pdf", PDF_BYTES)

    assert response.status_code == 202

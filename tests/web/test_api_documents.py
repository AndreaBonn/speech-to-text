from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sbobina.course_registry import find_by_key
from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.document_store import mark_failed
from sbobina.web.job_models import JobConfig
from sbobina.web.job_store import JobStore

BASE_URL = "http://127.0.0.1:8765"
COURSES_URL = "/api/v1/courses"
PDF_BYTES = b"%PDF-1.4\n%%EOF"
EXE_BYTES = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 64


def make_client(tmp_path: Path, settings: Settings | None = None) -> TestClient:
    app = create_app(
        settings=settings if settings is not None else Settings(), data_dir=tmp_path
    )
    return TestClient(app=app, base_url=BASE_URL, headers={"Origin": BASE_URL})


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    transport = make_client(tmp_path=tmp_path)
    yield transport
    transport.close()


def upload(
    client: TestClient, key: str, filename: str, content: bytes, **kwargs: Any
) -> Any:
    return client.post(
        f"{COURSES_URL}/{key}/documents",
        files={"file": (filename, content, "application/octet-stream")},
        **kwargs,
    )


def test_create_document_accepted_and_queued(client: TestClient) -> None:
    response = upload(client, "fisica", "Manuale.pdf", PDF_BYTES)
    assert response.status_code == 202
    data = response.json()["data"]
    assert data["status"] == "extracting"
    assert data["filename"] == "Manuale.pdf"
    assert data["kind"] == "pdf"
    assert data["size"] == len(PDF_BYTES)


def test_create_document_empty_course_key_is_conflict(client: TestClient) -> None:
    response = client.post(
        f"{COURSES_URL}//documents",
        files={"file": ("manuale.pdf", PDF_BYTES, "application/octet-stream")},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "COURSE_REQUIRED"


def test_create_document_too_large_is_rejected(tmp_path: Path) -> None:
    with make_client(
        tmp_path=tmp_path, settings=Settings(course_doc_max_mb=1)
    ) as client:
        oversized = PDF_BYTES + b"a" * (1024 * 1024 + 1)
        response = upload(client, "fisica", "grande.pdf", oversized)
        assert response.status_code == 413
        assert list((tmp_path / "courses").glob("*/documents/*/original.pdf")) == []


def test_create_document_unsupported_kind_is_rejected(
    client: TestClient, tmp_path: Path
) -> None:
    response = upload(client, "fisica", "malware.pdf", EXE_BYTES)
    assert response.status_code == 415
    documents_dirs = list((tmp_path / "courses").glob("*/documents"))
    assert documents_dirs == [] or list(documents_dirs[0].glob("*")) == []


@pytest.mark.parametrize(
    ("filename", "status", "kind"),
    [
        ("finto.pdf", 415, None),
        ("Appunti.md", 202, "md"),
        ("appunti.txt", 202, "txt"),
    ],
)
def test_create_document_text_kind_comes_from_uploaded_name(
    client: TestClient, filename: str, status: int, kind: str | None
) -> None:
    response = upload(client, "fisica", filename, b"MZfake ma testo UTF-8 valido")
    assert response.status_code == status
    if kind is not None:
        assert response.json()["data"]["kind"] == kind


def test_path_traversal_filename_is_contained(
    client: TestClient, tmp_path: Path
) -> None:
    response = upload(client, "fisica", "../../etc/passwd.pdf", PDF_BYTES)
    assert response.status_code == 202
    doc_id = response.json()["data"]["id"]
    matches = list((tmp_path / "courses").glob(f"*/documents/{doc_id}/original.pdf"))
    assert len(matches) == 1
    assert "etc" not in str(matches[0].relative_to(tmp_path))
    traversal_targets = list(tmp_path.parent.glob("etc/passwd.pdf"))
    assert traversal_targets == []


def test_list_documents_paginated_newest_first(client: TestClient) -> None:
    first = upload(client, "fisica", "uno.pdf", PDF_BYTES).json()["data"]["id"]
    second = upload(client, "fisica", "due.pdf", PDF_BYTES).json()["data"]["id"]
    response = client.get(f"{COURSES_URL}/fisica/documents", params={"per_page": 1})
    body = response.json()
    assert response.status_code == 200
    assert body["meta"] == {"page": 1, "per_page": 1, "total": 2, "total_pages": 2}
    assert body["data"][0]["id"] == second
    second_page = client.get(
        f"{COURSES_URL}/fisica/documents", params={"page": 2, "per_page": 1}
    ).json()
    assert second_page["data"][0]["id"] == first


def test_list_documents_unregistered_course_is_empty(client: TestClient) -> None:
    response = client.get(f"{COURSES_URL}/sconosciuto/documents")
    assert response.status_code == 200
    assert response.json() == {
        "data": [],
        "meta": {"page": 1, "per_page": 20, "total": 0, "total_pages": 0},
    }


def test_get_document_not_found(client: TestClient) -> None:
    response = client.get(f"{COURSES_URL}/fisica/documents/missing")
    assert response.status_code == 404


def test_get_document_page_not_found_while_extracting(client: TestClient) -> None:
    doc_id = upload(client, "fisica", "uno.pdf", PDF_BYTES).json()["data"]["id"]
    response = client.get(f"{COURSES_URL}/fisica/documents/{doc_id}/pages/1")
    assert response.status_code == 404


def test_download_document_sets_headers(client: TestClient) -> None:
    doc_id = upload(client, "fisica", "Manuale.pdf", PDF_BYTES).json()["data"]["id"]
    response = client.get(f"{COURSES_URL}/fisica/documents/{doc_id}/file")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert 'filename="Manuale.pdf"' in response.headers["content-disposition"]
    assert response.content == PDF_BYTES


def test_delete_document_busy_while_extracting(client: TestClient) -> None:
    doc_id = upload(client, "fisica", "uno.pdf", PDF_BYTES).json()["data"]["id"]
    response = client.delete(f"{COURSES_URL}/fisica/documents/{doc_id}")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DOCUMENT_BUSY"


def test_delete_document_removes_it(client: TestClient, tmp_path: Path) -> None:
    uploaded = upload(client, "fisica", "uno.pdf", PDF_BYTES).json()["data"]
    mark_failed(
        courses_dir=tmp_path / "courses",
        course_id=uploaded["course_id"],
        doc_id=uploaded["id"],
        code="EXTRACTION_FAILED",
    )
    response = client.delete(f"{COURSES_URL}/fisica/documents/{uploaded['id']}")
    assert response.status_code == 204
    assert (
        client.get(f"{COURSES_URL}/fisica/documents/{uploaded['id']}").status_code
        == 404
    )


def test_create_document_foreign_origin_rejected(client: TestClient) -> None:
    response = upload(
        client,
        "fisica",
        "uno.pdf",
        PDF_BYTES,
        headers={"Origin": "http://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_delete_document_foreign_origin_rejected(client: TestClient) -> None:
    doc_id = upload(client, "fisica", "uno.pdf", PDF_BYTES).json()["data"]["id"]
    response = client.delete(
        f"{COURSES_URL}/fisica/documents/{doc_id}",
        headers={"Origin": "http://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_create_document_failure_after_upload_leaves_no_orphans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_enqueue(document: object) -> object:
        raise OSError("disk full")

    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(
        app=app,
        base_url=BASE_URL,
        headers={"Origin": BASE_URL},
        raise_server_exceptions=False,
    ) as client:
        monkeypatch.setattr(app.state.extraction_worker, "enqueue_new", broken_enqueue)
        response = upload(client, "chimica", "manuale.pdf", PDF_BYTES)
        courses = client.get(COURSES_URL).json()["data"]

    assert response.status_code == 500
    assert list((tmp_path / "courses").glob("*/documents/*")) == []
    assert [course["key"] for course in courses] == []


def test_rejected_upload_does_not_register_a_new_course(client: TestClient) -> None:
    rejected = upload(client, "biologia", "malware.pdf", EXE_BYTES)
    accepted = upload(client, "fisica", "manuale.pdf", PDF_BYTES)

    assert (rejected.status_code, accepted.status_code) == (415, 202)
    keys = [course["key"] for course in client.get(COURSES_URL).json()["data"]]
    assert keys == ["fisica"]


def test_upload_registers_the_lecture_label_not_the_url_key(tmp_path: Path) -> None:
    JobStore(data_dir=tmp_path).create(
        config=JobConfig(subject="Diritto Privato"), source_name="lezione.m4a"
    )
    with make_client(tmp_path=tmp_path) as client:
        upload(client, "diritto privato", "manuale.pdf", PDF_BYTES)

    course = find_by_key(courses_dir=tmp_path / "courses", key="diritto privato")
    assert course is not None
    assert course.label == "Diritto Privato"


@pytest.mark.parametrize("doc_id", ["..", "..%2F..", "not-a-uuid"])
def test_document_routes_reject_ids_that_are_not_generated_ids(
    client: TestClient, tmp_path: Path, doc_id: str
) -> None:
    upload(client, "fisica", "manuale.pdf", PDF_BYTES)
    base = f"{COURSES_URL}/fisica/documents/{doc_id}"

    statuses = {
        client.get(base).status_code,
        client.get(f"{base}/file").status_code,
        client.delete(base).status_code,
    }

    assert statuses <= {404, 405}
    assert list((tmp_path / "courses").glob("*/course.json")) != []

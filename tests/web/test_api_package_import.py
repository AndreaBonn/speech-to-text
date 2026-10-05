import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from package_import_api_fixtures import (
    IMPORT_URL,
    SUCCESS,
    ImportProbe,
    client,
    probe,
    upload,
)
from package_import_fixtures import LECTURE_COUNT, make_package

from sbobina.course_registry import get_or_create
from sbobina.web.document_store import iter_documents
from sbobina.web.package_import_worker import PackageImportOutcome, PackageImportStatus

__all__ = ["client", "probe"]


@pytest.mark.parametrize("warning", [None, "già importato il 2026-10-05"])
def test_import_valid_or_reimport_returns_course_and_cleans_upload(
    client: TestClient, probe: ImportProbe, warning: str | None
) -> None:
    probe.outcome = replace(SUCCESS, warning=warning)
    response = upload(client=client)
    assert response.status_code == 201
    assert response.json() == {
        "data": {
            "course_id": "new-course",
            "course_label": "Fisica",
            "warning": warning,
        }
    }
    assert probe.payloads == [b"package"]
    assert len(probe.sources) == 1
    assert not probe.sources[0].exists()


ERROR_CASES = [
    (PackageImportStatus.REJECTED, "PACKAGE_TOO_LARGE", 413, "Too many members"),
    (PackageImportStatus.REJECTED, "PACKAGE_INVALID", 422, "Missing manifest.json"),
    (
        PackageImportStatus.REJECTED,
        "PACKAGE_VERSION_UNSUPPORTED",
        422,
        "Package format version 2 is newer than 1",
    ),
    (PackageImportStatus.BUSY, "PACKAGE_IMPORT_BUSY", 409, "Another import running"),
    (PackageImportStatus.STORAGE_ERROR, "PACKAGE_STORAGE_FAILED", 507, "Disk full"),
    (PackageImportStatus.RESOURCE_EXHAUSTED, "PACKAGE_FAILED", 503, "Out of memory"),
    (PackageImportStatus.FAILED, "PACKAGE_IMPORT_FAILED", 500, "Child crashed"),
    (PackageImportStatus.TIMEOUT, "PACKAGE_IMPORT_TIMEOUT", 503, "Timed out"),
]


@pytest.mark.parametrize(
    "case",
    ERROR_CASES,
    ids=[
        "too_large",
        "invalid",
        "future_version",
        "busy",
        "storage",
        "memory",
        "crash",
        "timeout",
    ],
)
def test_import_error_mapping_cleans_upload(
    client: TestClient,
    probe: ImportProbe,
    case: tuple[PackageImportStatus, str, int, str],
) -> None:
    status, code, http_status, message = case
    probe.outcome = PackageImportOutcome(status=status, code=code, message=message)
    response = upload(client=client)
    assert response.status_code == http_status
    error = response.json()["error"]
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == code
    assert error["details"] == []
    assert "pacchetto" in error["message"].lower()
    # The specific message follows the code, never the wording of the cause.
    assert ("versione più recente" in error["message"]) == (
        code == "PACKAGE_VERSION_UNSUPPORTED"
    )
    assert probe.payloads == [b"package"]
    assert len(probe.sources) == 1
    assert not probe.sources[0].exists()


def test_import_and_greedy_course_routes_remain_distinct(
    client: TestClient, probe: ImportProbe, tmp_path: Path
) -> None:
    for key in ("import", "fisica/import"):
        get_or_create(courses_dir=tmp_path / "courses", key=key, label=key)
        response = client.post(
            url=f"/api/v1/courses/{key}/rename", json={"label": f"{key} nuovo"}
        )
        assert response.status_code == 200
        assert response.json()["data"]["key"] == f"{key} nuovo"
        assert client.get(url=f"/api/v1/courses/{key} nuovo/export").status_code == 200
    assert probe.sources == []
    assert upload(client=client).status_code == 201
    assert probe.payloads == [b"package"]


def test_import_missing_file_is_validation_error(
    client: TestClient, probe: ImportProbe
) -> None:
    response = client.post(url=IMPORT_URL, data={"wrong": "field"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"][0]["field"] == "body.file"
    assert probe.sources == []
    assert upload(client=client).status_code == 201
    assert len(probe.sources) == 1


def test_import_origin_is_checked(client: TestClient, probe: ImportProbe) -> None:
    response = client.post(
        url=IMPORT_URL,
        headers={"Origin": "http://localhost:9999"},
        files={"file": ("course.zip", b"package")},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert probe.sources == []
    assert upload(client=client).status_code == 201
    assert probe.payloads == [b"package"]


def test_import_real_exported_package_end_to_end(
    client: TestClient, tmp_path: Path
) -> None:
    package = make_package(directory=tmp_path)
    response = upload(client=client, content=package.read_bytes())
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["course_label"] == "Fisica"
    assert data["warning"] is None
    assert (tmp_path / "courses" / data["course_id"] / "course.json").is_file()
    assert len(list((tmp_path / "jobs").glob("*/audio.json"))) == LECTURE_COUNT
    documents = list(
        iter_documents(courses_dir=tmp_path / "courses", course_id=data["course_id"])
    )
    assert len(documents) == 1
    assert documents[0].filename == "Notes.txt"


def test_import_real_package_is_searchable_and_listed_at_once(
    client: TestClient, tmp_path: Path
) -> None:
    # T077: no restart and no manual reindex between import and search.
    package = make_package(directory=tmp_path)
    data = upload(client=client, content=package.read_bytes()).json()["data"]
    imported_jobs = {
        path.parent.name for path in (tmp_path / "jobs").glob("*/audio.json")
    }

    lectures = client.get(url="/api/v1/search", params={"q": "lezione"}).json()
    documents = client.get(url="/api/v1/search", params={"q": "notes"}).json()
    courses = client.get(url="/api/v1/courses").json()["data"]

    lecture_hits = {item["id"] for item in lectures["data"] if "passages" in item}
    assert imported_jobs and imported_jobs <= lecture_hits
    assert [item["kind"] for item in documents["data"]] == ["document"]
    assert data["course_label"] in json.dumps(courses, ensure_ascii=False)


def test_import_killed_before_course_rename_leaves_no_visible_lectures(
    client: TestClient, tmp_path: Path
) -> None:
    # T092: lectures are renamed into place before the course (B7). Removing
    # the published course reproduces a kill between the two renames.
    package = make_package(directory=tmp_path)
    data = upload(client=client, content=package.read_bytes()).json()["data"]
    lectures = [path.parent for path in (tmp_path / "jobs").glob("*/job.json")]
    # Indexed while the course existed, so the index must also drop them.
    assert client.get(url="/api/v1/search", params={"q": "lezione"}).json()["data"]
    shutil.rmtree(tmp_path / "courses" / data["course_id"])

    courses = client.get(url="/api/v1/courses").json()["data"]
    jobs = client.get(url="/api/v1/jobs").json()["data"]

    assert len(lectures) == LECTURE_COUNT
    assert courses == []
    assert jobs == []
    search = client.get(url="/api/v1/search", params={"q": "lezione"}).json()
    assert search["data"] == []
    with TestClient(app=client.app, base_url="http://127.0.0.1:8765"):
        pass
    assert [path for path in lectures if path.exists()] == []

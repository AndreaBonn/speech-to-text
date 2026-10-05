import io
from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path
from typing import IO
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from package_fixtures import NOW, ORIGINAL, TRANSCRIPT, PackageFixture, seed_package

from sbobina.package_export import ExportRequest, write_package
from sbobina.package_models import Manifest
from sbobina.settings import Settings
from sbobina.web import api_package
from sbobina.web.app import create_app
from sbobina.web.course_dependencies import review_clock
from sbobina.web.job_models import JobConfig

BASE_URL = "http://127.0.0.1:8765"


@pytest.fixture
def course_data(tmp_path: Path) -> PackageFixture:
    return seed_package(tmp_path=tmp_path, label="Fisica/Uno")


@pytest.fixture
def app(course_data: PackageFixture) -> FastAPI:
    app = create_app(settings=Settings(), data_dir=course_data.store.jobs_dir.parent)
    app.dependency_overrides[review_clock] = lambda: NOW
    return app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    transport = TestClient(app=app, base_url=BASE_URL)
    yield transport
    transport.close()


def test_export_zip_manifest_is_coherent(client: TestClient) -> None:
    response = client.get(url="/api/v1/courses/fisica/uno/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="Fisica-Uno-2026-10-05.sbobina.zip"; '
        "filename*=utf-8''Fisica-Uno-2026-10-05.sbobina.zip"
    )
    with ZipFile(file=io.BytesIO(initial_bytes=response.content)) as archive:
        manifest = Manifest.model_validate_json(
            json_data=archive.read(name="manifest.json")
        )
        assert manifest.course.label == "Fisica/Uno"
        assert len(manifest.inventory) == 12
        assert set(archive.namelist()) == {"manifest.json"} | {
            entry.path for entry in manifest.inventory
        }
        for entry in manifest.inventory:
            data = archive.read(name=entry.path)
            assert entry.sha256 == sha256(data).hexdigest()
            assert entry.size == len(data)


def test_export_download_closes_its_temporary_file(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    targets: list[IO[bytes]] = []

    def record_write(target: IO[bytes], request: ExportRequest) -> None:
        write_package(target=target, request=request)
        targets.append(target)

    monkeypatch.setattr(api_package, "write_package", record_write)
    response = client.get(url="/api/v1/courses/fisica/uno/export")
    assert response.status_code == 200
    assert response.content.startswith(b"PK")
    assert len(targets) == 1
    assert targets[0].closed


def test_export_missing_course_returns_404(client: TestClient) -> None:
    response = client.get(url="/api/v1/courses/missing/export")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_export_docs_query_excludes_both_payloads(
    client: TestClient, course_data: PackageFixture
) -> None:
    excluded = course_data.document_ids[0]
    response = client.get(
        url="/api/v1/courses/fisica/uno/export",
        params={"docs": f" {excluded},unknown,{excluded}, "},
    )
    assert response.status_code == 200
    with ZipFile(file=io.BytesIO(initial_bytes=response.content)) as archive:
        manifest = Manifest.model_validate_json(
            json_data=archive.read(name="manifest.json")
        )
        assert manifest.options.excluded_document_ids == {excluded}
        assert archive.read(name="documents/1/original.txt") == ORIGINAL
        assert "documents/1/text.json" in archive.namelist()
        assert "documents/0/text.json" not in archive.namelist()
        assert "documents/0/original.txt" not in archive.namelist()


def test_export_and_nested_document_route_resolve_same_course(
    client: TestClient, course_data: PackageFixture
) -> None:
    prefix = "/api/v1/courses/fisica/uno"
    exported = client.get(url=f"{prefix}/export", params={"docs": ""})
    downloaded = client.get(
        url=f"{prefix}/documents/{course_data.document_ids[0]}/file"
    )
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/zip"
    assert downloaded.status_code == 200
    assert downloaded.content == ORIGINAL
    assert (
        downloaded.headers["content-disposition"] == 'attachment; filename="Notes.txt"'
    )


def test_export_lecture_only_course_packs_its_lectures(
    client: TestClient, course_data: PackageFixture
) -> None:
    # F49: a course whose lectures were only transcribed has no registry
    # record; exporting it must not 404, and must not create one either.
    store = course_data.store
    lecture = store.create(config=JobConfig(subject="Storia"), source_name="Lezione")
    (store.jobs_dir / str(lecture.id) / "audio.json").write_text(
        data=TRANSCRIPT.decode(), encoding="utf-8"
    )
    before = sorted(path.name for path in store.courses_dir.iterdir())

    response = client.get(url="/api/v1/courses/storia/export")

    assert response.status_code == 200
    with ZipFile(file=io.BytesIO(response.content)) as archive:
        manifest = Manifest.model_validate_json(archive.read("manifest.json"))
        names = archive.namelist()
    assert manifest.course.label == "Storia"
    assert sum(name.endswith("/transcript.json") for name in names) == 1
    assert sorted(path.name for path in store.courses_dir.iterdir()) == before


OLDER_SPELLINGS = 5


def test_export_lecture_only_course_takes_the_newest_spelling(
    client: TestClient, course_data: PackageFixture
) -> None:
    # Same rule as the course list (group_courses): the newest lecture names it.
    # The newest is created first, and update() keeps created_at, so the older
    # ones are backdated by rewriting job.json. Several older lectures make a
    # label picked in file-system order fail most runs.
    store = course_data.store
    newer = store.create(config=JobConfig(subject="Storia Antica"))
    records = [newer]
    for _ in range(OLDER_SPELLINGS):
        older = store.create(config=JobConfig(subject="storia antica"))
        backdated = older.model_copy(
            update={"created_at": newer.created_at.replace(year=2020)}
        )
        (store.jobs_dir / str(older.id) / "job.json").write_text(
            data=backdated.model_dump_json(), encoding="utf-8"
        )
        records.append(older)
    for record in records:
        (store.jobs_dir / str(record.id) / "audio.json").write_text(
            data=TRANSCRIPT.decode(), encoding="utf-8"
        )

    response = client.get(url="/api/v1/courses/storia antica/export")

    with ZipFile(file=io.BytesIO(response.content)) as archive:
        manifest = Manifest.model_validate_json(archive.read("manifest.json"))
    assert manifest.course.label == "Storia Antica"

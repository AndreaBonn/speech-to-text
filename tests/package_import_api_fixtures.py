import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from sbobina.settings import Settings
from sbobina.web import package_import_worker
from sbobina.web.app import create_app
from sbobina.web.package_import_worker import (
    PackageImportOptions,
    PackageImportOutcome,
    PackageImportStatus,
)

PORT = 8765
BASE_URL = f"http://127.0.0.1:{PORT}"
IMPORT_URL = "/api/v1/courses/import"
SUCCESS = PackageImportOutcome(
    status=PackageImportStatus.IMPORTED, course_id="new-course", course_label="Fisica"
)


@dataclass
class ImportProbe:
    outcome: PackageImportOutcome = SUCCESS
    sources: list[Path] = field(default_factory=list)
    payloads: list[bytes] = field(default_factory=list)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(
        settings=Settings(web_port=PORT, web_max_upload_mb=1), data_dir=tmp_path
    )
    transport = TestClient(app=app, base_url=BASE_URL, headers={"Origin": BASE_URL})
    yield transport
    transport.close()


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ImportProbe:
    result = ImportProbe()

    def run_import(
        source: Path,
        data_dir: Path,
        now: datetime,
        options: PackageImportOptions = package_import_worker.DEFAULT_OPTIONS,
    ) -> PackageImportOutcome:
        assert source.is_file()
        assert data_dir == tmp_path
        assert now.utcoffset() is not None
        with pytest.raises(RuntimeError, match="no running event loop"):
            asyncio.get_running_loop()
        result.sources.append(source)
        result.payloads.append(source.read_bytes())
        return result.outcome

    monkeypatch.setattr(package_import_worker, "run_package_import", run_import)
    return result


def upload(client: TestClient, content: bytes = b"package") -> Response:
    response: Response = client.post(
        url=IMPORT_URL,
        files={"file": ("course.sbobina.zip", content, "application/zip")},
    )
    return response

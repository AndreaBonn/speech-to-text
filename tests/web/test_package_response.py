import asyncio
import io
import tempfile
from collections.abc import AsyncGenerator, AsyncIterable
from pathlib import Path
from typing import IO, Any, cast
from zipfile import ZipFile

import pytest
from package_fixtures import NOW, seed_package

from sbobina.flashcard_scheduler import Scheduler
from sbobina.package_models import Manifest
from sbobina.settings import Settings
from sbobina.web import api_package
from sbobina.web.app import create_app
from sbobina.web.course_dependencies import ReviewServices
from sbobina.web.job_models import JobStatus


def spy_temporary_files(monkeypatch: pytest.MonkeyPatch) -> list[IO[bytes]]:
    created: list[IO[bytes]] = []
    real = tempfile.TemporaryFile

    def spy(*args: Any, **kwargs: Any) -> IO[bytes]:
        handle: IO[bytes] = real(*args, **kwargs)
        created.append(handle)
        return handle

    monkeypatch.setattr(api_package, "TemporaryFile", spy)
    return created


async def collect(iterator: AsyncIterable[Any]) -> bytes:
    return b"".join([bytes(chunk) async for chunk in iterator])


def test_export_response_streams_package_with_no_named_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Nothing named on disk once the route returns: a download that is
    # aborted half-way has no zip left to clean up.
    data = seed_package(tmp_path=tmp_path)
    temporary_dir = tmp_path / "tmp"
    temporary_dir.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temporary_dir))
    created = spy_temporary_files(monkeypatch=monkeypatch)
    services = ReviewServices(
        store=data.store, settings=Settings(), now=NOW, scheduler=Scheduler()
    )

    response = api_package.export_course(
        key=data.course.key, listed=data.course, services=services, docs=""
    )

    assert list(temporary_dir.iterdir()) == []
    assert response.media_type == "application/zip"
    assert response.headers["content-disposition"] == (
        'attachment; filename="Fisica-2026-10-05.sbobina.zip"; '
        "filename*=utf-8''Fisica-2026-10-05.sbobina.zip"
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    body = asyncio.run(collect(iterator=response.body_iterator))
    assert int(response.headers["content-length"]) == len(body)
    with ZipFile(file=io.BytesIO(body)) as archive:
        manifest = Manifest.model_validate_json(
            json_data=archive.read(name="manifest.json")
        )
    assert len(manifest.inventory) == 12
    assert [handle.closed for handle in created] == [True]


def test_export_stream_closed_early_closes_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = seed_package(tmp_path=tmp_path)
    created = spy_temporary_files(monkeypatch=monkeypatch)
    services = ReviewServices(
        store=data.store, settings=Settings(), now=NOW, scheduler=Scheduler()
    )
    response = api_package.export_course(
        key=data.course.key, listed=data.course, services=services, docs=""
    )
    # export_course hands Starlette its own async generator.
    iterator = cast(AsyncGenerator[bytes, None], response.body_iterator)

    async def read_one_chunk_then_disconnect() -> bytes:
        first = await anext(iterator)
        await iterator.aclose()
        return first

    first = asyncio.run(read_one_chunk_then_disconnect())

    assert first.startswith(b"PK")
    assert [handle.closed for handle in created] == [True]


def test_export_write_failure_closes_temporary_and_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = seed_package(tmp_path=tmp_path)
    # A finished lecture without its transcript makes the write fail.
    record = data.store.get(job_id=data.job_id)
    data.store.update(record=record.model_copy(update={"status": JobStatus.DONE}))
    (data.store.jobs_dir / data.job_id / "audio.json").unlink()
    created = spy_temporary_files(monkeypatch=monkeypatch)
    services = ReviewServices(
        store=data.store, settings=Settings(), now=NOW, scheduler=Scheduler()
    )

    with pytest.raises(FileNotFoundError):
        api_package.export_course(
            key=data.course.key, listed=data.course, services=services, docs=""
        )

    assert [handle.closed for handle in created] == [True]


def test_create_app_static_mount_preserves_asset_path(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    assert app.url_path_for("static", path="tokens.css") == "/static/tokens.css"


def test_content_disposition_keeps_accented_label_in_utf8_form() -> None:
    header = api_package.content_disposition(filename="Diritto-è-2026.sbobina.zip")

    assert header == (
        'attachment; filename="Diritto---2026.sbobina.zip"; '
        "filename*=utf-8''Diritto-%C3%A8-2026.sbobina.zip"
    )
    header.encode(encoding="latin-1")

from functools import partial
from pathlib import Path
from typing import IO, NoReturn

import pytest
from fastapi.testclient import TestClient
from package_import_api_fixtures import (
    IMPORT_URL,
    ImportProbe,
    client,
    probe,
    upload,
)
from starlette.datastructures import FormData
from starlette.formparsers import MultiPartParser

from sbobina.web.upload_limit import BYTES_PER_MB, FORM_OVERHEAD_BYTES

__all__ = ["client", "probe"]


@pytest.mark.parametrize("trailing_slash", [False, True])
def test_import_oversized_request_rejected_before_parser_or_disk(
    client: TestClient,
    probe: ImportProbe,
    monkeypatch: pytest.MonkeyPatch,
    trailing_slash: bool,
) -> None:
    parsed: list[str] = []
    original = MultiPartParser.parse

    async def parse(parser: MultiPartParser) -> FormData:
        parsed.append("parsed")
        return await original(parser)

    monkeypatch.setattr(MultiPartParser, "parse", parse)
    response = client.post(
        url=IMPORT_URL + ("/" if trailing_slash else ""),
        files={"file": ("large.zip", b"x" * (BYTES_PER_MB + FORM_OVERHEAD_BYTES))},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert response.json()["error"]["details"] == []
    assert parsed == []
    assert probe.sources == []
    assert upload(client=client).status_code == 201
    assert parsed == ["parsed"]
    assert probe.payloads == [b"package"]


def test_import_file_limit_excludes_multipart_overhead(
    client: TestClient, probe: ImportProbe
) -> None:
    response = upload(client=client, content=b"x" * (BYTES_PER_MB + 1))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PACKAGE_TOO_LARGE"
    assert probe.sources == []
    assert upload(client=client, content=b"x" * BYTES_PER_MB).status_code == 201
    assert probe.payloads == [b"x" * BYTES_PER_MB]
    assert len(probe.sources) == 1
    assert not probe.sources[0].exists()


def test_import_undeclared_length_is_rejected(
    client: TestClient, probe: ImportProbe
) -> None:
    response = client.post(url=IMPORT_URL, content=iter([b"package"]))
    assert response.status_code == 411
    assert response.json()["error"]["code"] == "LENGTH_REQUIRED"
    assert response.json()["error"]["details"] == []
    assert probe.sources == []
    assert upload(client=client).status_code == 201
    assert probe.payloads == [b"package"]


def fail_copy(
    paths: list[Path], fsrc: IO[bytes], fdst: IO[bytes], length: int
) -> NoReturn:
    fdst.write(b"partial")
    fdst.flush()
    path = Path(fdst.name)
    assert path.read_bytes() == b"partial"
    paths.append(path)
    raise OSError("Disk full /private/path")


def test_import_partial_write_failure_cleans_upload(
    client: TestClient, probe: ImportProbe, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sbobina.web import api_package_import

    paths: list[Path] = []
    with monkeypatch.context() as patch:
        patch.setattr(
            api_package_import, "copyfileobj", partial(fail_copy, paths=paths)
        )
        response = upload(client=client)
    assert response.status_code == 507
    assert response.json() == {
        "error": {
            "code": "PACKAGE_STORAGE_FAILED",
            "message": "Impossibile salvare il pacchetto su disco. Verifica lo spazio disponibile e i permessi.",
            "details": [],
        }
    }
    assert len(paths) == 1
    assert not paths[0].exists()
    assert probe.sources == []
    assert upload(client=client).status_code == 201
    assert probe.payloads == [b"package"]


def test_import_temporary_creation_failure_returns_storage_error(
    client: TestClient, probe: ImportProbe, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sbobina.web import api_package_import

    def fail_temporary(prefix: str) -> NoReturn:
        raise OSError("Permission denied /private/path")

    with monkeypatch.context() as patch:
        patch.setattr(api_package_import, "TemporaryDirectory", fail_temporary)
        response = upload(client=client)
    assert response.status_code == 507
    assert response.json()["error"]["code"] == "PACKAGE_STORAGE_FAILED"
    assert probe.sources == []
    assert upload(client=client).status_code == 201
    assert probe.payloads == [b"package"]

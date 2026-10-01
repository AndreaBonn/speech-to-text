from collections.abc import Iterator

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from sbobina.web.upload_limit import UploadLimitMiddleware

LIMIT_BYTES = 1000


@pytest.fixture
def reached() -> list[str]:
    return []


@pytest.fixture
def client(reached: list[str]) -> TestClient:
    async def endpoint(request: Request) -> PlainTextResponse:
        await request.body()
        reached.append(request.method)
        return PlainTextResponse("ok")

    inner = Starlette(routes=[Route("/api/v1/jobs", endpoint, methods=["GET", "POST"])])
    inner.add_middleware(
        UploadLimitMiddleware, path="/api/v1/jobs", max_bytes=LIMIT_BYTES
    )
    return TestClient(inner)


def test_upload_over_limit_is_rejected_before_reading_body(
    client: TestClient, reached: list[str]
) -> None:
    response = client.post("/api/v1/jobs", content=b"x" * (LIMIT_BYTES + 1))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert reached == []


def test_upload_without_content_length_is_rejected(
    client: TestClient, reached: list[str]
) -> None:
    def chunks() -> Iterator[bytes]:
        yield b"x" * 10

    response = client.post("/api/v1/jobs", content=chunks())

    assert response.status_code == 411
    assert response.json()["error"]["code"] == "LENGTH_REQUIRED"
    assert reached == []


def test_upload_within_limit_reaches_endpoint(
    client: TestClient, reached: list[str]
) -> None:
    response = client.post("/api/v1/jobs", content=b"x" * LIMIT_BYTES)

    assert response.status_code == 200
    assert reached == ["POST"]


def test_other_methods_are_not_limited(client: TestClient, reached: list[str]) -> None:
    response = client.get("/api/v1/jobs")

    assert response.status_code == 200
    assert reached == ["GET"]

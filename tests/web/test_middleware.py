import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sbobina.settings import Settings
from sbobina.web.app import create_app

BASE_URL = "http://127.0.0.1:8765"
# Plan C4 (S4): defence in depth for formulas rendered by KaTeX.
EXPECTED_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'"
)
INLINE_SCRIPT = re.compile(pattern=r"<script(?![^>]*\bsrc=)[^>]*>")
PAGES = ["/", "/corsi", "/ripasso", "/storico", "/modelli", "/confronto"]


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(web_port=8765), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as transport:
        yield transport


@pytest.mark.parametrize("path", PAGES)
def test_html_page_carries_the_content_security_policy(
    client: TestClient, path: str
) -> None:
    response = client.get(url=path)

    assert response.status_code == 200
    assert response.headers["Content-Security-Policy"] == EXPECTED_CSP


def test_json_response_has_no_content_security_policy(client: TestClient) -> None:
    response = client.get(url="/api/v1/courses")

    assert response.status_code == 200
    assert "Content-Security-Policy" not in response.headers


def test_html_error_page_carries_the_policy_and_json_error_does_not(
    client: TestClient,
) -> None:
    page = client.get(url="/lettore/00000000-0000-4000-8000-000000000000")
    api = client.get(url="/api/v1/jobs/00000000-0000-4000-8000-000000000000")

    assert page.status_code == 404
    assert page.headers["content-type"].startswith("text/html")
    assert page.headers["Content-Security-Policy"] == EXPECTED_CSP
    assert api.status_code == 404
    assert "Content-Security-Policy" not in api.headers


@pytest.mark.parametrize("path", PAGES)
def test_html_page_has_no_inline_script(client: TestClient, path: str) -> None:
    # script-src 'self' would block an inline script silently.
    html = client.get(url=path).text

    assert "<script" in html
    assert INLINE_SCRIPT.findall(html) == []

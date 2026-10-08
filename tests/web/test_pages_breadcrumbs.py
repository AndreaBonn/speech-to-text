"""S1: pages below a course show a Corsi › <corso> path instead of a loose course link."""

from pathlib import Path

from fastapi.testclient import TestClient
from page_fixtures import BASE_URL, write_course_document

from sbobina.settings import Settings
from sbobina.web.app import create_app


def _breadcrumbs(body: str) -> str:
    return body.split('<nav class="breadcrumbs"')[1].split("</nav>")[0]


def test_document_page_shows_course_path(tmp_path: Path) -> None:
    _, doc_id = write_course_document(tmp_path=tmp_path, filename="dispensa.pdf")
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get(f"/corsi/fisica/documenti/{doc_id}").text

    crumbs = _breadcrumbs(body)
    assert '<a href="/corsi">Corsi</a>' in crumbs
    assert '<a href="/corsi?corso=fisica">Fisica</a>' in crumbs
    assert 'class="reader__subtitle"' not in body


def test_pages_without_path_render_no_breadcrumbs(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/storico").text

    assert 'class="breadcrumbs"' not in body
    assert '<h1 class="page-title">Storico</h1>' in body

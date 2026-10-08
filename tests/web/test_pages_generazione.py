from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from generation_api_fixtures import _register_course, _store
from page_fixtures import BASE_URL
from test_practice_store import make_generation

from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.generation_store import generation_path


def make_generation_on_disk(tmp_path: Path, key: str = "fisica") -> str:
    course_id = _register_course(tmp_path=tmp_path, key=key)
    courses_dir = _store(tmp_path=tmp_path).courses_dir
    return make_generation(courses_dir=courses_dir, course_id=course_id).id


def test_generation_page_returns_shell_with_ids_and_math_assets(tmp_path: Path) -> None:
    # A card made from a generation links here (F51): the route must exist.
    generation_id = make_generation_on_disk(tmp_path=tmp_path)
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get(f"/corsi/fisica/generazioni/{generation_id}")

    assert response.status_code == 200
    body = response.text
    assert 'id="generazione-root"' in body
    assert f'data-generation-id="{generation_id}"' in body
    assert 'data-course-key="fisica"' in body
    assert "/static/js/corso-generazioni-dettaglio.js" in body
    assert "/static/js/generazione.js" in body
    assert "katex.min.js" in body
    rail = body.split('class="rail__list"')[1].split("</ul>")[0]
    active_link = rail.split('aria-current="page"')[1].split("</a>")[0]
    assert active_link.endswith(">Corsi")


def test_generation_page_unknown_generation_is_404(tmp_path: Path) -> None:
    make_generation_on_disk(tmp_path=tmp_path)
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get(f"/corsi/fisica/generazioni/{uuid4()}")

    assert response.status_code == 404
    assert "Generazione non trovata" in response.text
    assert 'id="generazione-root"' not in response.text


def test_generation_page_generation_of_another_course_is_404(tmp_path: Path) -> None:
    generation_id = make_generation_on_disk(tmp_path=tmp_path, key="fisica")
    _register_course(tmp_path=tmp_path, key="chimica")
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        found = client.get(f"/corsi/fisica/generazioni/{generation_id}")
        other = client.get(f"/corsi/chimica/generazioni/{generation_id}")

    assert found.status_code == 200
    assert other.status_code == 404


def test_generation_page_non_uuid_id_is_404(tmp_path: Path) -> None:
    make_generation_on_disk(tmp_path=tmp_path)
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get("/corsi/fisica/generazioni/non-un-uuid")

    assert response.status_code == 404
    assert "Generazione non trovata" in response.text


def test_generation_page_corrupted_record_says_damaged_and_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # A24: a corrupted record must not look like a wrong id with no trace.
    generation_id = make_generation_on_disk(tmp_path=tmp_path)
    course_id = _register_course(tmp_path=tmp_path, key="fisica")
    courses_dir = _store(tmp_path=tmp_path).courses_dir
    generation_path(
        courses_dir=courses_dir, course_id=course_id, gen_id=generation_id
    ).write_text("{non json", encoding="utf-8")
    caplog.set_level("WARNING", logger="sbobina")
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get(f"/corsi/fisica/generazioni/{generation_id}")

    assert response.status_code == 503
    assert "il file è danneggiato" in response.text
    # The startup scan logs the same file too: only the page's own record counts.
    page_logs = [
        r.getMessage() for r in caplog.records if r.module == "pages_generazione"
    ]
    assert any(generation_id in message for message in page_logs)


def test_generation_page_non_uuid_id_returns_404_without_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    make_generation_on_disk(tmp_path=tmp_path)
    caplog.set_level("WARNING", logger="sbobina")
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get(url="/corsi/fisica/generazioni/non-un-uuid")

    assert response.status_code == 404
    assert "Generazione non trovata" in response.text
    # The corrupted-record test pairs this absence with an actual page warning.
    page_logs = [r for r in caplog.records if r.module == "pages_generazione"]
    assert page_logs == []

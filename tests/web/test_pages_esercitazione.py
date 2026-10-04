from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from generation_api_fixtures import _register_course, _store
from page_fixtures import BASE_URL
from test_practice_store import make_generation

from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.practice_store import create_attempt


def make_attempt_on_disk(tmp_path: Path, key: str = "fisica") -> tuple[str, str]:
    course_id = _register_course(tmp_path=tmp_path, key=key)
    courses_dir = _store(tmp_path=tmp_path).courses_dir
    generation = make_generation(courses_dir=courses_dir, course_id=course_id)
    attempt = create_attempt(
        courses_dir=courses_dir, course_id=course_id, generation=generation
    )
    return generation.id, attempt.id


def test_practice_page_returns_shell_with_attempt_ids(tmp_path: Path) -> None:
    generation_id, attempt_id = make_attempt_on_disk(tmp_path=tmp_path)
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get(f"/corsi/fisica/esercitazioni/{attempt_id}")

    assert response.status_code == 200
    body = response.text
    assert 'id="esercitazione-root"' in body
    assert f'data-attempt-id="{attempt_id}"' in body
    assert f'data-generation-id="{generation_id}"' in body
    assert 'data-course-key="fisica"' in body
    assert "/static/js/esercitazione.js" in body
    rail = body.split('class="rail__list"')[1].split("</ul>")[0]
    active_link = rail.split('aria-current="page"')[1].split("</a>")[0]
    assert active_link.endswith(">Corsi")


def test_practice_page_unknown_attempt_is_404(tmp_path: Path) -> None:
    make_attempt_on_disk(tmp_path=tmp_path)
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get(f"/corsi/fisica/esercitazioni/{uuid4()}")

    assert response.status_code == 404
    assert "Esercitazione non trovata" in response.text
    assert 'id="esercitazione-root"' not in response.text


def test_practice_page_attempt_of_another_course_is_404(tmp_path: Path) -> None:
    _, attempt_id = make_attempt_on_disk(tmp_path=tmp_path, key="fisica")
    _register_course(tmp_path=tmp_path, key="chimica")
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        found = client.get(f"/corsi/fisica/esercitazioni/{attempt_id}")
        other = client.get(f"/corsi/chimica/esercitazioni/{attempt_id}")

    assert found.status_code == 200
    assert other.status_code == 404

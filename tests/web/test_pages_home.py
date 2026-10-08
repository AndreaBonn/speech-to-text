"""N1-N3: the upload form speaks of courses, hides the AI model until needed."""

from pathlib import Path

from fastapi.testclient import TestClient
from page_fixtures import BASE_URL

from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.job_models import JobConfig
from sbobina.web.job_store import JobStore


def _home(tmp_path: Path) -> str:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body: str = client.get("/").text
    return body


def test_subject_field_is_called_corso_and_suggests_existing_courses(
    tmp_path: Path,
) -> None:
    store = JobStore(data_dir=tmp_path)
    store.create(config=JobConfig(subject="Diritto"))
    store.create(config=JobConfig(subject="Fisica"))

    body = _home(tmp_path=tmp_path)

    assert '<label class="field__label" for="subject">Corso</label>' in body
    assert 'list="subject-courses"' in body
    datalist = body.split('<datalist id="subject-courses">')[1].split("</datalist>")[0]
    assert '<option value="Diritto">' in datalist
    assert '<option value="Fisica">' in datalist


def test_ai_model_field_is_hidden_until_correction_is_on(tmp_path: Path) -> None:
    body = _home(tmp_path=tmp_path)

    assert "Correggi gli errori con l&#39;AI locale" in body or (
        "Correggi gli errori con l'AI locale" in body
    )
    field = body.split('id="ollama-field"')[1].split(">")[0]
    assert "hidden" in field


def test_queue_heading_says_in_progress_and_recent(tmp_path: Path) -> None:
    body = _home(tmp_path=tmp_path)

    assert (
        '<h2 id="queue-heading" class="section-title">In corso e recenti</h2>' in body
    )
    assert "/static/js/queue-select.js" in body

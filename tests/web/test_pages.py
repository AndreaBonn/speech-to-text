from pathlib import Path

from fastapi.testclient import TestClient

from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.job_models import JobConfig
from sbobina.web.job_store import JobStore

BASE_URL = "http://127.0.0.1:8765"
FORM_FIELD_NAMES = (
    'name="file"',
    'name="subject"',
    'name="correct"',
    'name="ollama_model"',
    'name="whisper_model"',
    'name="beam_size"',
    'name="vad_filter"',
    'name="condition_on_previous_text"',
    'name="uncertain_threshold"',
)


def test_index_returns_form_with_expected_fields(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get("/")

    assert response.status_code == 200
    body = response.text
    for field in FORM_FIELD_NAMES:
        assert field in body


def test_static_tokens_css_is_served(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get("/static/tokens.css")

    assert response.status_code == 200
    assert "--color-accent" in response.text


def test_storico_page_returns_table_shell(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get("/storico")

    assert response.status_code == 200
    body = response.text
    assert 'id="storico-tbody"' in body
    assert 'id="storico-pagination"' in body
    assert "/static/js/storico.js" in body


def test_modelli_page_returns_catalogue_shell(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get("/modelli")

    assert response.status_code == 200
    body = response.text
    assert 'id="models-whisper-tbody"' in body
    assert 'id="ollama-download-form"' in body
    assert "/static/js/modelli.js" in body


def test_confronto_page_returns_form_shell(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get("/confronto")

    assert response.status_code == 200
    body = response.text
    assert 'id="wer-form"' in body
    assert 'id="wer-reference"' in body
    assert "/static/js/confronto.js" in body


def test_rail_disables_reader_link_without_a_done_job(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get("/")

    assert 'aria-disabled="true"' in response.text
    assert ">Lettore<" in response.text


def test_reader_page_returns_shell_for_an_existing_job(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(
        config=JobConfig(subject="Fisica"), source_name="lezione1.m4a"
    )
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get(f"/lettore/{record.id}")

    assert response.status_code == 200
    body = response.text
    assert f'data-job-id="{record.id}"' in body
    assert "lezione1.m4a" in body
    assert 'id="reader-text"' in body
    assert 'id="reader-points"' in body
    assert 'id="audio-bar"' in body
    assert f"/api/v1/jobs/{record.id}/audio" in body
    assert f"/api/v1/jobs/{record.id}/files/md" in body
    assert "/static/js/reader.js" in body


def test_reader_page_returns_404_for_missing_job(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get("/lettore/does-not-exist")

    assert response.status_code == 404
    assert "/storico" in response.text

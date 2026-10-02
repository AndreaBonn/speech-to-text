from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import JsonValue

from sbobina.settings import Settings
from sbobina.web import pages
from sbobina.web.app import create_app
from sbobina.web.job_models import JobConfig, JobStatus, LectureMeta
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


OLLAMA_READY: dict[str, JsonValue] = {
    "status": "ready",
    "message": "Ollama è pronto.",
    "models": [{"model": "qwen3.5:2b", "size": 1, "parameter_size": "2B"}],
}
WHISPER_MODELS: list[dict[str, JsonValue]] = [
    {
        "name": "large-v3-turbo",
        "downloaded": True,
        "recommended_gpu": False,
        "recommended_cpu": True,
    },
    {
        "name": "medium",
        "downloaded": False,
        "recommended_gpu": False,
        "recommended_cpu": False,
    },
]


@pytest.fixture(autouse=True)
def _models() -> object:
    """Keep the index page off the real Ollama server and Hugging Face cache."""
    with (
        patch.object(pages, "ollama_status", return_value=OLLAMA_READY),
        patch.object(pages, "list_whisper_models", return_value=WHISPER_MODELS),
    ):
        yield


def test_index_lists_models_with_state_and_profile(tmp_path: Path) -> None:
    app = create_app(settings=Settings(ollama_model="qwen3.5:9b"), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/").text

    assert ">large-v3-turbo · scaricato · consigliato</option>" in body
    assert ">medium · da scaricare, 1,5 GB</option>" in body
    assert (
        '<option value="qwen3.5:9b" selected>qwen3.5:9b · da scaricare all&#39;avvio'
        in body
    )
    assert ">qwen3.5:2b · installato</option>" in body
    assert '<option value="__altro__">Altro modello…</option>' in body
    assert "Precisione: bassa · Velocità: alta" in body
    assert 'data-profile-for="auto">' in body
    assert 'data-profile-for="medium" hidden>' in body


def test_index_tells_why_ollama_models_are_missing(tmp_path: Path) -> None:
    down: dict[str, JsonValue] = {
        "status": "not_running",
        "message": "Ollama non è disponibile. Avvia ollama serve.",
        "models": [],
    }
    app = create_app(settings=Settings(ollama_model="qwen3.5:9b"), data_dir=tmp_path)
    with (
        patch.object(pages, "ollama_status", return_value=down),
        TestClient(app=app, base_url=BASE_URL) as client,
    ):
        body = client.get("/").text

    assert "Ollama non è disponibile. Avvia ollama serve." in body
    assert '<option value="qwen3.5:9b" selected>qwen3.5:9b</option>' in body


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


def test_corsi_page_returns_shell(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get("/corsi")

    assert response.status_code == 200
    body = response.text
    assert 'id="corsi-list"' in body
    assert 'id="corsi-detail"' in body
    assert "/static/js/corsi.js" in body


def test_corsi_page_marks_its_rail_entry_active(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/corsi").text

    assert ">Corsi<" in body
    assert 'class="rail__link rail__link--active"' in body


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


def test_reader_course_field_falls_back_to_subject(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig(subject="Fisica"), source_name="a.m4a")
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get(f"/lettore/{record.id}").text

    assert 'id="course-input"' in body
    assert 'value="Fisica"' in body
    assert 'maxlength="100"' in body
    assert "/static/js/course-field.js" in body


def test_reader_course_field_prefers_meta_and_escapes_it(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig(subject="Fisica"), source_name="a.m4a")
    store.write_meta(job_id=str(record.id), meta=LectureMeta(course='Analisi "1" <b>'))
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get(f"/lettore/{record.id}").text

    assert 'value="Analisi &#34;1&#34; &lt;b&gt;"' in body
    assert 'value="Fisica"' not in body


def test_reader_page_returns_404_for_missing_job(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get("/lettore/does-not-exist")

    assert response.status_code == 404
    assert "/storico" in response.text


def test_pages_show_the_transcriber_brand(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/").text

    assert '<div class="rail__brand">Transcriber</div>' in body
    assert "<title>Nuova trascrizione · Transcriber</title>" in body


def test_rail_links_reader_to_the_newest_done_job(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    done = store.create(config=JobConfig(), source_name="vecchia.m4a")
    store.update(record=done.model_copy(update={"status": JobStatus.DONE}))
    store.create(config=JobConfig(), source_name="in-coda.m4a")
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/").text

    assert f'href="/lettore/{done.id}"' in body
    assert 'aria-disabled="true"' not in body


@pytest.mark.parametrize(
    ("subject", "expected_title"), [("Fisica", "Fisica"), (None, "Lezione del ")]
)
def test_reader_page_without_source_name_falls_back_to_subject_then_date(
    tmp_path: Path, subject: str | None, expected_title: str
) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig(subject=subject))
    if subject is None:
        expected_title += record.created_at.strftime("%d/%m/%Y")
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get(f"/lettore/{record.id}").text

    assert f'<h2 class="reader__title">{expected_title}</h2>' in body


def test_reader_page_loads_the_deep_link_after_the_reader(tmp_path: Path) -> None:
    record = JobStore(data_dir=tmp_path).create(config=JobConfig())
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get(f"/lettore/{record.id}").text

    assert "/static/js/reader-link.js" in body
    assert body.index("/static/js/reader.js") < body.index("/static/js/reader-link.js")


def test_corsi_page_has_the_search_form(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/corsi").text

    assert 'id="search-form"' in body
    assert 'id="search-input"' in body
    assert 'id="search-course"' in body
    assert 'id="search-results"' in body
    assert body.index("/static/js/dom.js") < body.index("/static/js/search.js")


def test_pages_apply_the_saved_theme_before_the_stylesheets(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/").text

    head = body.split("</head>")[0]
    assert '<script src="/static/js/theme.js"></script>' in head
    assert head.index("theme.js") < head.index("tokens.css")


def test_rail_has_the_theme_toggle_button(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/storico").text

    assert 'id="theme-toggle"' in body
    assert 'type="button"' in body.split('id="theme-toggle"')[1].split(">")[0]


def test_static_theme_script_is_served(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get("/static/js/theme.js")

    assert response.status_code == 200
    assert "data-theme" in response.text or "dataset.theme" in response.text


def test_index_explains_beam_size_with_the_recommended_value(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/").text

    help_button = body.split('class="toggletip__button"')[1].split(">")[0]
    assert 'aria-describedby="beam_size-tip"' in help_button
    tip = body.split('id="beam_size-tip"')[1].split("</span>")[0]
    assert "Consigliato: 5" in tip

import re
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from page_fixtures import (
    BASE_URL,
    FORM_FIELD_NAMES,
    _models,
)
from pydantic import JsonValue
from starlette.requests import Request

from sbobina.settings import Settings
from sbobina.web import pages
from sbobina.web.app import create_app

__all__ = ["_models"]


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


def test_index_includes_engine_warning_slot_and_scripts(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/").text

    assert (
        '<div id="engine-warning-banner" class="banner-region" aria-live="polite"></div>'
        in body
    )
    assert '<script src="/static/js/engine-warning.js"></script>' in body
    assert '<script src="/static/js/engine-form.js" defer></script>' in body


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


def test_pages_show_the_transcriber_brand(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/").text

    assert '<div class="rail__brand">Transcriber</div>' in body
    assert "<title>Nuova trascrizione · Transcriber</title>" in body


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
        response = client.get(url="/static/js/theme.js")

    assert response.status_code == 200
    assert 'root.setAttribute("data-theme", theme);' in response.text


def test_ripasso_page_returns_shell(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get("/ripasso")

    assert response.status_code == 200
    body = response.text
    assert 'id="ripasso-summary-list"' in body
    assert 'id="ripasso-card"' in body
    assert "/static/js/ripasso.js" in body


def test_ripasso_page_marks_its_rail_entry_active(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get(url="/ripasso").text

    link = re.search(pattern=r"<a\b[^>]*>Ripasso</a>", string=body)
    assert link is not None
    assert 'href="/ripasso"' in link.group()
    assert 'aria-current="page"' in link.group()


def test_ripasso_page_places_its_rail_entry_after_corsi(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get(url="/ripasso").text

    assert ">Ripasso<" in body
    rail = body.split('class="rail__list"')[1].split("</ul>")[0]
    assert rail.index(">Corsi<") < rail.index(">Ripasso<")


def test_index_explains_beam_size_with_the_recommended_value(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/").text

    help_button = body.split('class="toggletip__button"')[1].split(">")[0]
    assert 'aria-describedby="beam_size-tip"' in help_button
    tip = body.split('id="beam_size-tip"')[1].split("</span>")[0]
    assert "Consigliato: 5" in tip


def test_index_non_list_ollama_models_renders_default_only(tmp_path: Path) -> None:
    app = create_app(settings=Settings(ollama_model="default-model"), data_dir=tmp_path)
    status: dict[str, JsonValue] = {"status": "ready", "message": "", "models": None}
    request = Request(scope={"type": "http", "app": app, "path": "/"})
    with patch.object(pages, "ollama_status", return_value=status):
        malformed = pages.index(request=request, store=app.state.job_store)
        status["models"] = [{"model": "installed-model"}]
        populated = pages.index(request=request, store=app.state.job_store)

    assert malformed.status_code == populated.status_code == 200
    assert b'value="default-model" selected' in bytes(malformed.body)
    assert b'value="installed-model"' not in bytes(malformed.body)
    assert b'value="installed-model"' in bytes(populated.body)


def test_ripasso_page_says_where_cards_come_from(tmp_path: Path) -> None:
    """P2: an empty deck explains how to fill it."""
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/ripasso").text

    sources = body.split('class="review__sources"')[1].split("</p>")[0]
    assert 'href="/corsi"' in sources
    for source in (
        "frasi da esame",
        "errori delle esercitazioni",
        "materiali di studio",
    ):
        assert source in " ".join(sources.split())


def test_modelli_page_has_the_in_use_slot_and_model_choice_script(
    tmp_path: Path,
) -> None:
    """M1/M2: the in-use line sits above the catalogue; the split loads first."""
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/modelli").text

    assert body.index('id="models-in-use"') < body.index('id="models-whisper-heading"')
    assert body.index("/static/js/modelli-scelta.js") < body.index(
        "/static/js/modelli.js"
    )

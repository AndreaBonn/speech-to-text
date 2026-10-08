from pathlib import Path

from fastapi.testclient import TestClient
from page_fixtures import BASE_URL

from sbobina.settings import Settings
from sbobina.web.app import create_app


def test_impostazioni_page_returns_shell(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get("/impostazioni")

    assert response.status_code == 200
    body = response.text
    assert "Motore per testi e studio" in body
    assert "Ordine dei modelli" in body
    assert "Chiavi API" in body
    assert "Trascrizione" in body
    assert "/static/js/settings-dom.js" in body
    assert "/static/js/settings-chain.js" in body
    assert "/static/js/settings-keys.js" in body
    assert "/static/js/impostazioni.js" in body


def test_impostazioni_page_has_the_semantic_search_section(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/impostazioni").text

    assert "Ricerca semantica" in body
    assert 'id="semantic-search-toggle"' in body
    assert 'id="semantic-model-select"' in body
    assert 'id="semantic-pull-command"' in body
    assert 'id="semantic-rebuild-dialog"' in body
    assert 'id="semantic-coverage-list"' in body
    assert "/static/js/retrieval-mode.js" in body
    assert "/static/js/settings-semantic-coverage.js" in body
    assert "/static/js/settings-semantic.js" in body
    assert body.index("/static/js/retrieval-mode.js") < body.index(
        "/static/js/settings-semantic.js"
    )
    assert body.index("/static/js/settings-semantic-coverage.js") < body.index(
        "/static/js/settings-semantic.js"
    )

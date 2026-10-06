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
    assert "/static/js/impostazioni.js" in body

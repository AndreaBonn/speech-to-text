"""S5 and R6: the rail groups the technical pages and names the last lecture."""

from pathlib import Path

from fastapi.testclient import TestClient
from page_fixtures import BASE_URL

from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.job_models import JobConfig, JobStatus
from sbobina.web.job_store import JobStore


def _rail(body: str) -> str:
    return body.split('<nav class="rail"')[1].split("</nav>")[0]


def _get(tmp_path: Path, url: str) -> str:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body: str = client.get(url).text
    return body


def test_rail_puts_technical_pages_under_strumenti(tmp_path: Path) -> None:
    rail = _rail(_get(tmp_path=tmp_path, url="/"))

    main, tools = rail.split('class="rail__group-title"')
    assert ">Strumenti<" in tools
    for label in ("Modelli", "Confronto (WER)", "Impostazioni"):
        assert f">{label}</a>" in tools
        assert f">{label}</a>" not in main
    for label in ("Nuova trascrizione", "Corsi", "Ripasso", "Storico"):
        assert f">{label}</a>" in main


def test_rail_names_the_last_lecture_instead_of_lettore(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    done = store.create(config=JobConfig(), source_name="possesso.m4a")
    store.update(record=done.model_copy(update={"status": JobStatus.DONE}))

    rail = _rail(_get(tmp_path=tmp_path, url="/"))

    link = rail.split(f'href="/lettore/{done.id}"')[1].split("</a>")[0]
    assert "Ultima lezione" in link
    assert "possesso.m4a" in link
    assert ">Lettore<" not in rail


def test_rail_without_lectures_keeps_a_disabled_last_lecture_entry(
    tmp_path: Path,
) -> None:
    rail = _rail(_get(tmp_path=tmp_path, url="/"))

    assert 'aria-disabled="true">Ultima lezione</span>' in rail

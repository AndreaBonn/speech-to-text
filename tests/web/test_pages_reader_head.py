"""Reader head: path, lecture title as heading, course line, hint, downloads."""

from pathlib import Path

from fastapi.testclient import TestClient
from page_fixtures import BASE_URL

from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.job_models import JobConfig, JobStatus
from sbobina.web.job_store import JobStore


def _done_job(tmp_path: Path, subject: str | None) -> str:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig(subject=subject), source_name="possesso.m4a")
    store.update(record=record.model_copy(update={"status": JobStatus.DONE}))
    return str(record.id)


def _get(tmp_path: Path, url: str) -> str:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body: str = client.get(url).text
    return body


def test_reader_heading_is_the_lecture_under_its_course_path(tmp_path: Path) -> None:
    """S1: no "Lettore" title; the lecture is the h1, its course the path."""
    job_id = _done_job(tmp_path=tmp_path, subject="Diritto")

    body = _get(tmp_path=tmp_path, url=f"/lettore/{job_id}")

    assert '<h1 class="page-title reader__title">possesso.m4a</h1>' in body
    assert '<h1 class="page-title">Lettore</h1>' not in body
    crumbs = body.split('<nav class="breadcrumbs"')[1].split("</nav>")[0]
    assert '<a href="/corsi?corso=diritto">Diritto</a>' in crumbs


def test_reader_without_course_has_no_path(tmp_path: Path) -> None:
    job_id = _done_job(tmp_path=tmp_path, subject=None)

    body = _get(tmp_path=tmp_path, url=f"/lettore/{job_id}")

    assert 'class="breadcrumbs"' not in body
    assert ">Assegna</button>" in body


def test_reader_course_is_a_line_with_an_edit_button(tmp_path: Path) -> None:
    """R3: the course form stays closed behind Modifica."""
    job_id = _done_job(tmp_path=tmp_path, subject="Diritto")

    body = _get(tmp_path=tmp_path, url=f"/lettore/{job_id}")

    assert '<strong id="course-current" data-course="Diritto">Diritto</strong>' in body
    edit = body.split('id="course-edit"')[1].split("</button>")[0]
    assert 'aria-controls="course-form"' in edit
    assert ">Modifica" in edit
    form = body.split('<form id="course-form"')[1].split(">")[0]
    assert "hidden" in form


def test_reader_tells_that_a_word_click_plays_the_audio(tmp_path: Path) -> None:
    """R4."""
    job_id = _done_job(tmp_path=tmp_path, subject="Diritto")

    body = _get(tmp_path=tmp_path, url=f"/lettore/{job_id}")

    assert "Clicca una parola per ascoltare l&#39;audio da quel punto." in body or (
        "Clicca una parola per ascoltare l'audio da quel punto." in body
    )


def test_reader_downloads_sit_in_one_menu_with_names_of_use(tmp_path: Path) -> None:
    """L3: one Scarica menu; the ids reader.js updates are still there."""
    job_id = _done_job(tmp_path=tmp_path, subject="Diritto")

    body = _get(tmp_path=tmp_path, url=f"/lettore/{job_id}")

    menu = body.split('<details class="download-menu reader__downloads"')[1].split(
        "</details>"
    )[0]
    assert ">Scarica</summary>" in menu
    for label in ("Documento Word (.docx)", "Testo semplice (.txt)", "Markdown (.md)"):
        assert label in menu
    for element_id in (
        "export-docx",
        "export-txt",
        "download-corrected-md",
        "download-report",
    ):
        assert f'id="{element_id}"' in menu
    assert "Scarica .md" not in body


def test_reader_offers_three_uncertainty_levels(tmp_path: Path) -> None:
    """R1: Nessuna, Le più dubbie (default), Tutte."""
    job_id = _done_job(tmp_path=tmp_path, subject="Diritto")

    body = _get(tmp_path=tmp_path, url=f"/lettore/{job_id}")

    picker = body.split('id="uncertain-level"')[1].split("</div>")[0]
    assert 'aria-labelledby="uncertain-level-label"' in picker
    for level, label in (
        ("none", "Nessuna"),
        ("most", "Le più dubbie"),
        ("all", "Tutte"),
    ):
        assert f'data-level="{level}"' in picker
        assert f">{label}</button>" in picker
    assert 'data-level="most" aria-pressed="true"' in picker

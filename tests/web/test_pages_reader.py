import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from page_fixtures import (
    BASE_URL,
    _models,
)

from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.job_models import JobConfig, JobStage, JobStatus, LectureMeta
from sbobina.web.job_store import JobStore

__all__ = ["_models"]


@pytest.mark.parametrize("imported,has_audio", [(False, "true"), (True, "false")])
def test_reader_page_exposes_audio_availability(
    tmp_path: Path, imported: bool, has_audio: str
) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig())
    store.update(
        record=record.model_copy(
            update={
                "status": JobStatus.DONE,
                "stage": JobStage.DONE,
                "imported": imported,
            }
        )
    )
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get(url=f"/lettore/{record.id}")

    assert response.status_code == 200
    assert f'data-job-id="{record.id}"' in response.text
    assert f'data-has-audio="{has_audio}"' in response.text
    # T082: an imported lecture has no audio file, so no player asks for one.
    assert ('id="audio-player"' in response.text) == (not imported)
    assert ("l'audio non è incluso" in response.text) == imported
    assert response.text.index("/static/js/reader-audio.js") < response.text.index(
        "/static/js/reader.js"
    )


def test_rail_disables_reader_link_without_a_done_job(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get(url="/")

    assert response.status_code == 200
    link = re.search(
        pattern=r"<span\b[^>]*>Ultima lezione</span>", string=response.text
    )
    assert link is not None
    assert 'aria-disabled="true"' in link.group()
    assert 'class="rail__link rail__link--disabled"' in link.group()


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
    assert body.index("/static/js/reader-words.js") < body.index("/static/js/reader.js")
    assert "/static/js/card-dialog.js" in body
    assert "/static/js/reader-cards.js" in body
    assert 'id="reader-card-trigger"' in body
    assert 'id="reader-card-dialog"' in body


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

    assert f'<h1 class="page-title reader__title">{expected_title}</h1>' in body


def test_reader_page_loads_the_deep_link_after_the_reader(tmp_path: Path) -> None:
    record = JobStore(data_dir=tmp_path).create(config=JobConfig())
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get(f"/lettore/{record.id}").text

    assert "/static/js/reader-link.js" in body
    assert body.index("/static/js/reader.js") < body.index("/static/js/reader-link.js")


def test_studio_page_returns_shell_for_an_existing_job(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig(subject="Fisica"), source_name="a.m4a")
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get(f"/studio/{record.id}")

    assert response.status_code == 200
    body = response.text
    assert f'data-job-id="{record.id}"' in body
    assert "a.m4a" in body
    assert 'id="study-chapters"' in body
    assert f'href="/lettore/{record.id}"' in body
    assert body.index("/static/js/dom.js") < body.index("/static/js/studio.js")


def test_studio_script_is_served_with_job_api_endpoint(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get(url="/static/js/studio.js")

    assert response.status_code == 200
    assert "/api/v1/jobs/" in response.text
    # No markup sink check here: test_untrusted_rendering.py covers studio.js.


def test_studio_page_returns_404_for_missing_job(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get("/studio/does-not-exist")

    assert response.status_code == 404
    assert 'id="study-chapters"' not in response.text


def test_reader_links_to_the_study_page(tmp_path: Path) -> None:
    record = JobStore(data_dir=tmp_path).create(config=JobConfig())
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get(f"/lettore/{record.id}").text

    assert f'href="/studio/{record.id}"' in body

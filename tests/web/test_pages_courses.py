from pathlib import Path

from fastapi.testclient import TestClient
from page_fixtures import (
    BASE_URL,
    _models,
    write_course_document,
)

from sbobina.settings import Settings
from sbobina.web.app import create_app

__all__ = ["_models"]


def test_corsi_page_returns_shell(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get("/corsi")

    assert response.status_code == 200
    body = response.text
    assert 'id="corsi-list"' in body
    assert 'id="corsi-detail"' in body
    assert "/static/js/corsi.js" in body
    assert "/static/js/corso-dettaglio.js" in body
    assert body.index("/static/js/dom.js") < body.index("/static/js/corso-dettaglio.js")
    assert body.index("/static/js/corso-dettaglio.js") < body.index(
        "/static/js/corsi.js"
    )
    assert body.index("/static/js/corsi.js") < body.index("/static/js/search.js")


def test_corsi_page_has_the_semantic_retrieval_status_line(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/corsi").text

    assert 'id="corsi-detail-retrieval"' in body
    assert "/static/js/retrieval-mode.js" in body
    assert "/static/js/corso-retrieval-status.js" in body
    assert body.index("/static/js/retrieval-mode.js") < body.index(
        "/static/js/corso-retrieval-status.js"
    )
    assert body.index("/static/js/corso-retrieval-status.js") < body.index(
        "/static/js/corso-dettaglio.js"
    )
    assert body.index("/static/js/retrieval-mode.js") < body.index(
        "/static/js/corso-chat-thread.js"
    )


def test_corsi_page_marks_its_rail_entry_active(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/corsi").text

    assert ">Corsi<" in body
    assert 'class="rail__link rail__link--active"' in body


def test_corsi_page_has_the_search_form(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/corsi").text

    assert 'id="search-form"' in body
    assert 'id="search-input"' in body
    assert 'id="search-course"' in body
    assert 'id="search-results"' in body
    assert body.index("/static/js/dom.js") < body.index("/static/js/search.js")


def test_corsi_page_includes_the_materials_section(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/corsi").text

    assert 'id="materials-list"' in body
    assert 'id="materials-dropzone"' in body
    assert 'id="materials-empty"' in body
    assert "/static/js/corso-materiali.js" in body
    assert body.index("/static/js/dom.js") < body.index("/static/js/corso-upload.js")
    assert body.index("/static/js/corso-upload.js") < body.index(
        "/static/js/corso-materiali.js"
    )
    assert body.index("/static/js/corso-materiali.js") < body.index(
        "/static/js/corso-dettaglio.js"
    )


def test_corsi_page_includes_the_exam_cues_section(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/corsi").text

    assert 'id="corsi-examcues"' in body
    assert 'id="examcues-toggle"' in body
    assert 'id="examcues-list"' in body
    assert 'id="examcues-empty"' in body
    assert "Mostra anche i segnali deboli" in body
    assert "/static/js/corso-frasi-esame.js" in body
    # The section reads its DOM builders from the render module at load time.
    assert (
        body.index("/static/js/dom.js")
        < body.index("/static/js/corso-frasi-esame-render.js")
        < body.index("/static/js/corso-frasi-esame.js")
    )
    assert body.index("/static/js/corso-frasi-esame.js") < body.index(
        "/static/js/corso-dettaglio.js"
    )
    # Deferred scripts run in order: the shared dialog must load first.
    assert body.index("/static/js/card-dialog.js") < body.index(
        "/static/js/exam-cue-cards.js"
    )


def test_documento_page_returns_shell_for_an_existing_document(tmp_path: Path) -> None:
    key, doc_id = write_course_document(tmp_path, "Manuale.pdf")
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get(f"/corsi/{key}/documenti/{doc_id}")

    assert response.status_code == 200
    body = response.text
    assert f'data-doc-id="{doc_id}"' in body
    assert "Manuale.pdf" in body
    assert 'id="document-text"' in body
    assert body.index("/static/js/dom.js") < body.index("/static/js/documento.js")


def test_documento_page_returns_404_for_missing_document(tmp_path: Path) -> None:
    key, _ = write_course_document(tmp_path, "Manuale.pdf")
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get(f"/corsi/{key}/documenti/does-not-exist")

    assert response.status_code == 404
    assert 'id="document-text"' not in response.text


def test_documento_page_returns_404_for_unregistered_course(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        response = client.get("/corsi/does-not-exist/documenti/doc-1")

    assert response.status_code == 404


def test_documento_page_escapes_a_malicious_filename(tmp_path: Path) -> None:
    safe_key, safe_doc_id = write_course_document(tmp_path, "Manuale.pdf")
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        baseline = client.get(f"/corsi/{safe_key}/documenti/{safe_doc_id}").text

    other_tmp_path = tmp_path / "other"
    key, doc_id = write_course_document(
        other_tmp_path, "Manuale<script>alert(1)</script>.pdf"
    )
    app = create_app(settings=Settings(), data_dir=other_tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get(f"/corsi/{key}/documenti/{doc_id}").text

    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    # The payload adds no real <script> tag: both pages load the same set.
    assert body.count("<script") == baseline.count("<script")


def test_corsi_page_has_attempts_and_mistakes_before_detail_script(
    tmp_path: Path,
) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/corsi").text

    assert 'id="corsi-attempts"' in body
    assert 'id="corsi-mistakes"' in body
    assert "Non hai ancora svolto esercitazioni" in body
    # corso-dettaglio.js reads window.SbobinaCoursePractice when it runs, so the
    # practice module and the result helpers it uses must load before it.
    assert body.index("/static/js/esercitazione-esito.js") < body.index(
        "/static/js/corso-esercitazioni.js"
    )
    assert body.index("/static/js/corso-esercitazioni.js") < body.index(
        "/static/js/corso-dettaglio.js"
    )


def test_corsi_page_has_package_export_and_import(tmp_path: Path) -> None:
    # T078: export dialog in the course detail, import in the course list.
    app = create_app(settings=Settings(), data_dir=tmp_path)
    with TestClient(app=app, base_url=BASE_URL) as client:
        body = client.get("/corsi").text

    for element in ('id="export-open"', 'id="export-dialog"', 'id="import-input"'):
        assert element in body
    assert "diritto d'autore" in body
    assert "voci e nomi di altri studenti" in body
    assert 'id="examcue-card-dialog"' in body  # moved to a partial, still there
    # Detail script calls SbobinaCourseExport, list reload is used by import.
    assert (
        body.index("/static/js/corso-export.js")
        < body.index("/static/js/corso-dettaglio.js")
        < body.index("/static/js/corsi.js")
        < body.index("/static/js/corsi-import.js")
    )

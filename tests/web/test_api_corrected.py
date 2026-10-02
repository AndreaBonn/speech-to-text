from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from typing import cast
from urllib.parse import quote

import pytest
from conftest import make_segment, make_transcript, make_word
from docx import Document
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sbobina.models import Transcript, load_transcript, save_transcript
from sbobina.settings import Settings
from sbobina.web.api_corrected import MAX_EDIT_CHARS
from sbobina.web.app import create_app
from sbobina.web.job_models import JobConfig, JobRecord, JobStatus
from sbobina.web.job_store import JobStore

BASE_URL = "http://127.0.0.1:8765"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(
        settings=Settings(paragraph_gap_s=2.0, paragraph_max_s=120.0),
        data_dir=tmp_path,
    )
    transport = TestClient(app=app, base_url=BASE_URL)
    yield transport
    transport.close()


def _store(client: TestClient) -> JobStore:
    store: JobStore = cast(FastAPI, client.app).state.job_store
    return store


def _transcript() -> Transcript:
    first = make_segment(
        [make_word("Il", 0.0), make_word(" processo", 0.4, 0.3), make_word(" è", 0.8)]
    )
    second = make_segment([make_word(" Poi", 10.0), make_word(" altro.", 10.4)])
    return make_transcript([first, second])


def _job(
    client: TestClient,
    status: JobStatus = JobStatus.DONE,
    subject: str | None = None,
    corrected: bool = True,
) -> tuple[JobRecord, Path]:
    store = _store(client)
    record = store.create(
        config=JobConfig(subject=subject), source_name="Lezione 3.m4a"
    )
    record = store.update(record=record.model_copy(update={"status": status}))
    directory = store.jobs_dir / str(record.id)
    save_transcript(transcript=_transcript(), path=directory / "audio.json")
    if corrected:
        save_transcript(
            transcript=_transcript(), path=directory / "audio.corretto.json"
        )
    return record, directory


def _all_text(payload: dict[str, object]) -> str:
    paragraphs = cast(list[list[dict[str, str]]], payload["paragraphs"])
    return "".join(word["text"] for paragraph in paragraphs for word in paragraph)


def test_export_docx_corrected_is_book_text_named_after_audio(
    client: TestClient,
) -> None:
    record, _ = _job(client, subject="Diritto privato")

    response = client.get(url=f"/api/v1/jobs/{record.id}/export/docx")

    assert response.status_code == 200
    assert response.headers["content-type"] == DOCX_TYPE
    assert response.headers["content-disposition"] == (
        f"attachment; filename*=utf-8''{quote('Lezione 3.corretto.docx')}"
    )
    texts = [p.text for p in Document(BytesIO(response.content)).paragraphs]
    assert texts == ["Diritto privato", "Il processo è", "Poi altro."]


def test_export_txt_original_uses_source_stem_as_title(client: TestClient) -> None:
    record, _ = _job(client)

    response = client.get(url=f"/api/v1/jobs/{record.id}/export/txt?variant=original")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert "Lezione%203.txt" in response.headers["content-disposition"]
    assert response.text == "Lezione 3\n\nIl processo è\n\nPoi altro.\n"


def test_export_without_source_name_or_subject_is_titled_by_date_and_ascii_named(
    client: TestClient,
) -> None:
    store = _store(client)
    record = store.create(config=JobConfig())
    record = store.update(record=record.model_copy(update={"status": JobStatus.DONE}))
    save_transcript(
        transcript=_transcript(),
        path=store.jobs_dir / str(record.id) / "audio.corretto.json",
    )

    response = client.get(url=f"/api/v1/jobs/{record.id}/export/txt")

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="audio.corretto.txt"'
    )
    created = record.created_at.strftime("%d/%m/%Y")
    assert response.text.startswith(f"Lezione del {created}\n\n")


def test_export_missing_corrected_variant_returns_404(client: TestClient) -> None:
    record, _ = _job(client, corrected=False)

    response = client.get(url=f"/api/v1/jobs/{record.id}/export/txt")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_edit_span_saves_json_rewrites_markdown_and_returns_reader(
    client: TestClient,
) -> None:
    record, directory = _job(client)

    response = client.patch(
        url=f"/api/v1/jobs/{record.id}/transcript/corrected",
        json={
            "start": 1,
            "end": 2,
            "expected": "processo",
            "text": "possesso",
            "revision": _revision(client=client, record=record),
        },
    )

    assert response.status_code == 200
    assert _all_text(response.json()["data"]) == "Il possesso è Poi altro."
    saved = load_transcript(directory / "audio.corretto.json")
    assert saved.words[1].text == " possesso"
    assert saved.words[1].corrected_from == "processo"
    assert "possesso" in (directory / "audio.corretto.md").read_text(encoding="utf-8")
    assert load_transcript(directory / "audio.json").words[1].text == " processo"


def test_edit_span_stale_text_returns_409_and_keeps_file(client: TestClient) -> None:
    record, directory = _job(client)

    response = client.patch(
        url=f"/api/v1/jobs/{record.id}/transcript/corrected",
        json={
            "start": 1,
            "end": 2,
            "expected": "altro",
            "text": "possesso",
            "revision": _revision(client=client, record=record),
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EDIT_CONFLICT"
    assert load_transcript(directory / "audio.corretto.json") == _transcript()


def test_edit_span_out_of_range_returns_422(client: TestClient) -> None:
    record, _ = _job(client)

    response = client.patch(
        url=f"/api/v1/jobs/{record.id}/transcript/corrected",
        json={
            "start": 4,
            "end": 9,
            "expected": "",
            "text": "x",
            "revision": _revision(client=client, record=record),
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_edit_span_while_job_runs_returns_409(client: TestClient) -> None:
    record, _ = _job(client, status=JobStatus.RUNNING)

    response = client.patch(
        url=f"/api/v1/jobs/{record.id}/transcript/corrected",
        json={
            "start": 1,
            "end": 2,
            "expected": "processo",
            "text": "possesso",
            "revision": _revision(client=client, record=record),
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JOB_IN_PROGRESS"


def test_edit_span_without_corrected_copy_returns_404(client: TestClient) -> None:
    record, _ = _job(client, corrected=False)

    response = client.patch(
        url=f"/api/v1/jobs/{record.id}/transcript/corrected",
        json={
            "start": 1,
            "end": 2,
            "expected": "processo",
            "text": "possesso",
            "revision": "missing",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_create_corrected_copies_original_once(client: TestClient) -> None:
    record, directory = _job(client, corrected=False)
    url = f"/api/v1/jobs/{record.id}/transcript/corrected"

    created = client.post(url=url)
    client.patch(
        url=url,
        json={
            "start": 1,
            "end": 2,
            "expected": "processo",
            "text": "x",
            "revision": _revision(client=client, record=record),
        },
    )
    again = client.post(url=url)

    assert created.status_code == 201
    assert created.json() == {"data": {"created": True}, "meta": {}}
    assert again.status_code == 200
    assert again.json() == {"data": {"created": False}, "meta": {}}
    assert load_transcript(directory / "audio.corretto.json").words[1].text == " x"
    assert (directory / "audio.corretto.md").is_file()


def _revision(client: TestClient, record: JobRecord) -> str:
    url = f"/api/v1/jobs/{record.id}/transcript?variant=corrected"
    revision: str = client.get(url=url).json()["meta"]["revision"]
    return revision


def test_edit_span_stale_revision_returns_409_even_if_text_matches(
    client: TestClient,
) -> None:
    record, directory = _job(client)
    url = f"/api/v1/jobs/{record.id}/transcript/corrected"
    seen_by_tab_b = _revision(client=client, record=record)
    # Tab A turns "è" (index 2) into two words: every later index shifts by one.
    tab_a = client.patch(
        url=url,
        json={
            "start": 2,
            "end": 3,
            "expected": "è",
            "text": "è poi",
            "revision": seen_by_tab_b,
        },
    )

    # Tab B still sees " Poi" at index 3; index 3 now holds " poi" from tab A.
    tab_b = client.patch(
        url=url,
        json={
            "start": 3,
            "end": 4,
            "expected": "poi",
            "text": "dopo",
            "revision": seen_by_tab_b,
        },
    )

    assert tab_a.status_code == 200
    assert tab_a.json()["meta"]["revision"] == _revision(client=client, record=record)
    assert tab_b.status_code == 409
    assert tab_b.json()["error"]["code"] == "EDIT_CONFLICT"
    saved = load_transcript(directory / "audio.corretto.json")
    assert [w.text for w in saved.words] == [
        "Il",
        " processo",
        " è",
        " poi",
        " Poi",
        " altro.",
    ]


def test_edit_span_without_revision_returns_422(client: TestClient) -> None:
    record, _ = _job(client)

    response = client.patch(
        url=f"/api/v1/jobs/{record.id}/transcript/corrected",
        json={"start": 1, "end": 2, "expected": "processo", "text": "possesso"},
    )

    assert response.status_code == 422
    fields = [detail["field"] for detail in response.json()["error"]["details"]]
    assert fields == ["body.revision"]


def test_create_corrected_while_job_runs_returns_409(client: TestClient) -> None:
    record, directory = _job(client, status=JobStatus.RUNNING, corrected=False)

    response = client.post(url=f"/api/v1/jobs/{record.id}/transcript/corrected")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JOB_IN_PROGRESS"
    assert not (directory / "audio.corretto.json").exists()


def test_edit_span_text_over_limit_returns_field_error(client: TestClient) -> None:
    record, _ = _job(client)

    response = client.patch(
        url=f"/api/v1/jobs/{record.id}/transcript/corrected",
        json={
            "start": 1,
            "end": 2,
            "expected": "processo",
            "text": "x" * (MAX_EDIT_CHARS + 1),
            "revision": _revision(client=client, record=record),
        },
    )

    assert response.status_code == 422
    fields = [detail["field"] for detail in response.json()["error"]["details"]]
    assert fields == ["body.text"]

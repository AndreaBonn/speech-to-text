from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from study_api_fixtures import client, create_job, job_store, set_study, write_material
from study_fixtures import QUOTE, transcript_fixture

from sbobina.models import save_transcript
from sbobina.web.job_models import JobStatus, StudyRun, StudyStatus

__all__ = ["client"]


def test_post_study_ready_job_returns_202(client: TestClient) -> None:
    record, _ = create_job(client=client)

    response = client.post(url=f"/api/v1/jobs/{record.id}/study")

    assert response.status_code == 202
    assert response.json() == {"data": {"status": "queued"}, "meta": {}}
    current = job_store(client=client).get(job_id=str(record.id))
    assert current.status == JobStatus.DONE
    assert current.study is not None and current.study.status == StudyStatus.QUEUED


def test_post_study_imported_lecture_returns_202_queued(client: TestClient) -> None:
    record, _ = create_job(client=client)
    store = job_store(client=client)
    store.update(record=record.model_copy(update={"imported": True}))

    response = client.post(url=f"/api/v1/jobs/{record.id}/study")

    assert response.status_code == 202
    assert response.json() == {"data": {"status": "queued"}, "meta": {}}
    current = store.get(job_id=str(record.id))
    assert current.imported is True
    assert current.status == JobStatus.DONE
    assert current.study is not None and current.study.status == StudyStatus.QUEUED


@pytest.mark.parametrize("status", [JobStatus.QUEUED, JobStatus.RUNNING])
def test_post_study_pipeline_active_returns_409(
    client: TestClient, status: JobStatus
) -> None:
    record, _ = create_job(client=client, status=status)

    response = client.post(url=f"/api/v1/jobs/{record.id}/study")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STUDY_NOT_READY"


@pytest.mark.parametrize("status", [StudyStatus.QUEUED, StudyStatus.RUNNING])
def test_post_study_duplicate_returns_409(
    client: TestClient, status: StudyStatus
) -> None:
    record, _ = create_job(client=client)
    study = StudyRun(status=status, updated_at=datetime.now(tz=UTC))
    set_study(client=client, record=record, study=study)

    response = client.post(url=f"/api/v1/jobs/{record.id}/study")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STUDY_ALREADY_QUEUED"


def test_post_study_missing_transcript_returns_409(client: TestClient) -> None:
    record, directory = create_job(client=client)
    (directory / "audio.json").unlink()

    response = client.post(url=f"/api/v1/jobs/{record.id}/study")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STUDY_NOT_READY"


def test_get_study_missing_material_returns_404(client: TestClient) -> None:
    record, _ = create_job(client=client)

    response = client.get(url=f"/api/v1/jobs/{record.id}/study")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "STUDY_NOT_FOUND"


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_study_missing_job_returns_404(client: TestClient, method: str) -> None:
    response = client.request(method=method, url=f"/api/v1/jobs/{uuid4()}/study")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("status", list(StudyStatus))
def test_get_study_without_material_returns_run_state(
    client: TestClient, status: StudyStatus
) -> None:
    record, _ = create_job(client=client)
    study = StudyRun(status=status, updated_at=datetime.now(tz=UTC))
    set_study(client=client, record=record, study=study)

    response = client.get(url=f"/api/v1/jobs/{record.id}/study")

    assert response.status_code == 200
    assert response.json() == {
        "data": {"study": study.model_dump(mode="json"), "material": None},
        "meta": {},
    }


def test_get_study_material_returns_exact_payload(client: TestClient) -> None:
    record, directory = create_job(client=client)
    material = write_material(directory=directory)
    citation = {
        "quote": QUOTE,
        "timestamp": 10.0,
        "paragrafo": 2,
        "href": f"/lettore/{record.id}?t=10.0&variant=original",
    }
    for items in ("summary", "concepts", "questions"):
        material["chapters"][0][items][0]["citations"] = [citation]
    material.update(discarded={"QUOTE_NOT_FOUND": 2}, stale=False, stale_dropped=0)

    response = client.get(url=f"/api/v1/jobs/{record.id}/study")

    assert response.status_code == 200
    assert response.json() == {
        "data": {"study": None, "material": material},
        "meta": {},
    }


def test_get_study_changed_render_options_recomputes_paragraph(
    client: TestClient,
) -> None:
    record, directory = create_job(client=client)
    write_material(directory=directory)
    url = f"/api/v1/jobs/{record.id}/study"
    before = client.get(url=url).json()["data"]["material"]
    cast(FastAPI, client.app).state.settings.paragraph_gap_s = 20.0

    after = client.get(url=url).json()["data"]["material"]

    old = before["chapters"][0]["summary"][0]["citations"][0]
    new = after["chapters"][0]["summary"][0]["citations"][0]
    assert old["paragrafo"] == 2 and new["paragrafo"] == 1
    assert old["timestamp"] == new["timestamp"] == 10.0


def test_get_study_patch_cited_word_drops_stale_items(client: TestClient) -> None:
    record, directory = create_job(client=client)
    save_transcript(
        transcript=transcript_fixture(), path=directory / "audio.corretto.json"
    )
    material = write_material(directory=directory, variant="corrected")
    url = f"/api/v1/jobs/{record.id}"
    before = client.get(url=f"{url}/study").json()["data"]["material"]

    edited = client.patch(
        url=f"{url}/transcript/corrected",
        json={
            "start": 4,
            "end": 5,
            "expected": "causa",
            "text": "ragione",
            "revision": material["source_revision"],
        },
    )
    after = client.get(url=f"{url}/study").json()["data"]["material"]

    assert edited.status_code == 200
    assert before["stale"] is False and before["stale_dropped"] == 0
    assert before["chapters"][0]["summary"][0]["citations"][0]["href"].endswith(
        "variant=corrected"
    )
    assert after["stale"] is True and after["stale_dropped"] == 3
    assert len(before["chapters"]) == 1 and after["chapters"] == []
    assert after["source_revision"] == material["source_revision"]


def test_get_study_failed_regeneration_keeps_material(client: TestClient) -> None:
    record, directory = create_job(client=client)
    write_material(directory=directory)
    study = StudyRun(
        status=StudyStatus.FAILED,
        updated_at=datetime.now(tz=UTC),
        error={"code": "OLLAMA_UNAVAILABLE"},
    )
    set_study(client=client, record=record, study=study)

    response = client.get(url=f"/api/v1/jobs/{record.id}/study")

    assert response.status_code == 200
    assert response.json()["data"]["study"] == study.model_dump(mode="json")
    assert response.json()["data"]["material"]["chapters"][0]["title"] == "Contratto"

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from generation_api_fixtures import _register_course, _store, _write_document
from practice_grading_fixtures import app, client, judge
from test_api_practice import make_url
from test_practice_store import make_generation

from sbobina.generation_models import GenerationSourceUsed
from sbobina.web.document_store import read_document, write_document
from sbobina.web.generation_store import generation_path, save_generation
from sbobina.web.practice_store import create_attempt

__all__ = ["app", "client", "judge"]
MISTAKES = "/api/v1/courses/fisica/mistakes"


@pytest.fixture
def attempt_url(tmp_path: Path) -> str:
    course_id = _register_course(tmp_path=tmp_path)
    courses_dir = _store(tmp_path=tmp_path).courses_dir
    generation = make_generation(courses_dir=courses_dir, course_id=course_id)
    doc_id = generation.questions[0].citations[0].doc_id
    assert doc_id is not None
    _write_document(
        tmp_path=tmp_path, course_id=course_id, doc_id=doc_id, filename="Book.pdf"
    )
    source = GenerationSourceUsed(
        doc_id=doc_id, sha256="a" * 64, job_id=None, revision=None
    )
    generation = replace(generation, sources=(source,))
    save_generation(courses_dir=courses_dir, course_id=course_id, record=generation)
    attempt = create_attempt(
        courses_dir=courses_dir, course_id=course_id, generation=generation
    )
    return f"{make_url(generation=generation)}/{attempt.id}"


def test_wrong_then_correct_removes_mistake(
    client: TestClient, attempt_url: str
) -> None:
    assert (
        client.post(url=f"{attempt_url}/answers/0", json={"choice": 0}).status_code
        == 200
    )
    mistakes = client.get(url=MISTAKES)
    assert mistakes.status_code == 200
    assert [
        (item["question_index"], item["outcome"]) for item in mistakes.json()["data"]
    ] == [(0, "errata")]
    collection = attempt_url.rsplit("/", 1)[0]
    new_id = client.post(url=collection).json()["data"]["id"]
    assert (
        client.post(
            url=f"{collection}/{new_id}/answers/0", json={"choice": 2}
        ).status_code
        == 200
    )
    assert client.get(url=MISTAKES).json()["data"] == []


def test_replaced_document_resolves_from_snapshot(
    client: TestClient,
    attempt_url: str,
    tmp_path: Path,
) -> None:
    client.post(url=f"{attempt_url}/answers/0", json={"choice": 0})
    first = client.get(url=MISTAKES)
    assert first.status_code == 200
    citation = first.json()["data"][0]["citations"][0]
    assert citation["status"] == "ok"
    assert "?p=1" in citation["href"]
    course_id = _register_course(tmp_path=tmp_path)
    courses_dir = _store(tmp_path=tmp_path).courses_dir
    doc_id = citation["href"].split("/")[-1].split("?")[0]
    document = read_document(
        courses_dir=courses_dir, course_id=course_id, doc_id=doc_id
    )
    write_document(courses_dir=courses_dir, document=replace(document, sha256="b" * 64))
    generation_path(
        courses_dir=courses_dir, course_id=course_id, gen_id=attempt_url.split("/")[-3]
    ).unlink()
    changed = client.get(url=MISTAKES).json()["data"][0]["citations"][0]
    assert changed["status"] == "source_modified"
    assert changed["href"] == citation["href"]


@pytest.mark.parametrize("parallel", [False, True])
def test_mistake_card_idempotent(
    client: TestClient, attempt_url: str, parallel: bool
) -> None:
    client.post(url=f"{attempt_url}/answers/0", json={"choice": 0})
    attempt_id = attempt_url.split("/")[-1]
    url = f"{MISTAKES}/{attempt_id}/0/card"
    if parallel:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(client.post, url=url) for _ in range(2)]
            responses = [future.result(timeout=10) for future in futures]
    else:
        responses = [client.post(url=url), client.post(url=url)]
    assert sorted(response.status_code for response in responses) == [200, 201]
    cards = [response.json()["data"] for response in responses]
    assert cards[0] == cards[1]
    assert cards[0]["anchor"] == {
        "kind": "generation",
        "generation_id": attempt_url.split("/")[-3],
        "question_index": 0,
    }
    assert cards[0]["front"] == "Question?"
    assert cards[0]["back"] == "Expected explanation"
    assert len(client.get(url="/api/v1/courses/fisica/cards").json()["data"]) == 1


def test_mistakes_pagination_and_scope(
    client: TestClient, attempt_url: str, tmp_path: Path
) -> None:
    for index in range(2):
        client.post(url=f"{attempt_url}/answers/{index}", json={"choice": 0})
    page = client.get(url=MISTAKES, params={"page": 2, "per_page": 1})
    assert page.status_code == 200
    assert page.json()["meta"] == {
        "page": 2,
        "per_page": 1,
        "total": 2,
        "total_pages": 2,
        "unavailable_attempts": [],
    }
    assert len(page.json()["data"]) == 1
    _register_course(tmp_path=tmp_path, key="altro")
    assert client.get(url=MISTAKES.replace("fisica", "altro")).json()["data"] == []
    assert client.get(url=MISTAKES, params={"page": 0}).status_code == 422


def test_card_requires_submitted_mistake(client: TestClient, attempt_url: str) -> None:
    attempt_id = attempt_url.split("/")[-1]
    assert client.post(url=f"{MISTAKES}/{attempt_id}/0/card").status_code == 404
    assert client.post(url=f"{MISTAKES}/{uuid4()}/0/card").status_code == 404
    client.post(url=f"{attempt_url}/answers/0", json={"choice": 0})
    assert client.post(url=f"{MISTAKES}/{attempt_id}/0/card").status_code == 201


def test_unreadable_attempt_does_not_hide_other_mistakes(
    client: TestClient, attempt_url: str, tmp_path: Path
) -> None:
    client.post(url=f"{attempt_url}/answers/0", json={"choice": 0})
    courses_dir = _store(tmp_path=tmp_path).courses_dir
    practice_dir = next(courses_dir.glob("*/practice/*.json")).parent
    bad_id = str(uuid4())
    (practice_dir / f"{bad_id}.json").write_text("{", encoding="utf-8")

    response = client.get(url=MISTAKES)

    assert response.status_code == 200
    assert [item["question_index"] for item in response.json()["data"]] == [0]
    assert response.json()["meta"]["unavailable_attempts"] == [bad_id]

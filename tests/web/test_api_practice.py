import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from generation_api_fixtures import _register_course, _store, client
from test_practice_models import make_attempt
from test_practice_store import make_generation

from sbobina.generation_models import (
    GenerationFormat,
    GenerationRecord,
    GenerationStatus,
)
from sbobina.practice_models import AnswerStatus, MultipleChoiceAnswer, PracticeAttempt
from sbobina.settings import Settings
from sbobina.web.api_practice import _attempt_payload
from sbobina.web.app import create_app
from sbobina.web.generation_store import generation_path, save_generation
from sbobina.web.practice_store import (
    create_attempt,
    load_attempt,
    practice_path,
    save_attempt,
)

__all__ = ["client"]
SECOND_PAGE_META = {"page": 2, "per_page": 2, "total": 3, "total_pages": 2}


def make_url(generation: GenerationRecord, key: str = "fisica") -> str:
    return f"/api/v1/courses/{key}/generations/{generation.id}/attempts"


def assert_hidden(payload: dict[str, Any], solution: str) -> None:
    assert payload["questions"][0]["question"] == "Question?"
    assert payload["questions"][0]["options"] == ["a", "b", "c", "d"]
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "solution" not in encoded
    assert "correct_index" not in encoded
    assert solution not in encoded


def test_add_attempt_done_persists_and_hides_solutions(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    courses_dir = _store(tmp_path=tmp_path).courses_dir
    generation = make_generation(courses_dir=courses_dir, course_id=course_id)
    response = client.post(url=make_url(generation=generation))
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["status"] == "in_progress"
    assert_hidden(payload=data, solution=generation.questions[0].solution)
    attempt = load_attempt(
        courses_dir=courses_dir, course_id=course_id, attempt_id=data["id"]
    )
    assert attempt.questions == generation.questions


@pytest.mark.parametrize("status", tuple(GenerationStatus))
def test_add_attempt_unready_or_summary_returns_expected_error(
    client: TestClient,
    tmp_path: Path,
    status: GenerationStatus,
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    courses_dir = _store(tmp_path=tmp_path).courses_dir
    generation = make_generation(courses_dir=courses_dir, course_id=course_id)
    record = replace(
        generation,
        status=status,
        questions=(),
        format=GenerationFormat.SUMMARY
        if status == GenerationStatus.DONE
        else generation.format,
        error="Failure" if status == GenerationStatus.FAILED else None,
    )
    save_generation(courses_dir=courses_dir, course_id=course_id, record=record)
    response = client.post(url=make_url(generation=record))
    assert response.status_code == (409 if status == GenerationStatus.FAILED else 422)
    assert response.json()["error"]["code"] == (
        "GENERATION_FAILED" if status == GenerationStatus.FAILED else "VALIDATION_ERROR"
    )


def test_get_attempt_deleted_generation_still_readable_and_hidden(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path, key="diritto/civile")
    courses_dir = _store(tmp_path=tmp_path).courses_dir
    generation = make_generation(courses_dir=courses_dir, course_id=course_id)
    attempt = create_attempt(
        courses_dir=courses_dir, course_id=course_id, generation=generation
    )
    url = f"{make_url(generation=generation, key='diritto/civile')}/{attempt.id}"
    before = client.get(url=url)
    generation_path(
        courses_dir=courses_dir, course_id=course_id, gen_id=generation.id
    ).unlink()
    after = client.get(url=url)
    assert before.status_code == after.status_code == 200
    assert before.json() == after.json()
    assert_hidden(
        payload=after.json()["data"], solution=generation.questions[0].solution
    )


@pytest.mark.parametrize("status", tuple(AnswerStatus))
def test_get_attempt_only_answered_question_reveals_solution(
    client: TestClient,
    tmp_path: Path,
    status: AnswerStatus,
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    courses_dir = _store(tmp_path=tmp_path).courses_dir
    generation = make_generation(courses_dir=courses_dir, course_id=course_id)
    hidden = replace(generation.questions[0], solution="Hidden explanation")
    generation = replace(generation, questions=(hidden, generation.questions[1]))
    attempt = create_attempt(
        courses_dir=courses_dir, course_id=course_id, generation=generation
    )
    answer = MultipleChoiceAnswer(
        answer_id=str(uuid4()), question_index=1, status=status, chosen_index=2
    )
    save_attempt(
        courses_dir=courses_dir,
        course_id=course_id,
        attempt=replace(attempt, answers=(answer,)),
    )
    response = client.get(url=f"{make_url(generation=generation)}/{attempt.id}")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["questions"][1]["solution"] == generation.questions[1].solution
    assert data["questions"][1]["correct_index"] == 2
    assert data["questions"][1]["citations"][0]["quote"] == "Original source"
    assert "solution" not in data["questions"][0]
    assert "correct_index" not in data["questions"][0]
    assert "Hidden explanation" not in response.text


def test_get_attempts_filters_before_pagination_and_hides_solutions(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    courses_dir = _store(tmp_path=tmp_path).courses_dir
    generation = make_generation(courses_dir=courses_dir, course_id=course_id)
    attempts = [
        create_attempt(
            courses_dir=courses_dir, course_id=course_id, generation=generation
        )
        for _ in range(3)
    ]
    set_attempt_mtimes(courses_dir=courses_dir, attempts=attempts)
    create_attempt(
        courses_dir=courses_dir,
        course_id=course_id,
        generation=replace(generation, id=str(uuid4())),
    )
    response = client.get(
        url=make_url(generation=generation), params={"page": 2, "per_page": 2}
    )
    assert response.status_code == 200
    assert response.json()["meta"] == SECOND_PAGE_META
    assert [item["id"] for item in response.json()["data"]] == [attempts[0].id]
    assert_hidden(
        payload=response.json()["data"][0], solution=generation.questions[0].solution
    )


def set_attempt_mtimes(courses_dir: Path, attempts: list[PracticeAttempt]) -> None:
    for timestamp, attempt in enumerate(attempts, start=1):
        path = practice_path(
            courses_dir=courses_dir, course_id=attempt.course_id, attempt_id=attempt.id
        )
        os.utime(path=path, times=(timestamp, timestamp))


def test_attempt_payload_unanswered_hidden_and_submitted_revealed() -> None:
    attempt = make_attempt()
    assert_hidden(
        payload=_attempt_payload(attempt=attempt),
        solution=attempt.questions[0].solution,
    )
    answer = MultipleChoiceAnswer(
        answer_id=str(uuid4()), question_index=1, chosen_index=2
    )
    payload = _attempt_payload(attempt=replace(attempt, answers=(answer,)))
    assert payload["questions"][1]["solution"] == attempt.questions[1].solution
    assert payload["questions"][1]["correct_index"] == 2
    assert "solution" not in payload["questions"][0]
    assert "correct_index" not in payload["questions"][0]


def test_create_app_practice_routes_registered(tmp_path: Path) -> None:
    app = create_app(settings=Settings(), data_dir=tmp_path)
    paths = app.openapi()["paths"]
    collection = "/api/v1/courses/{key}/generations/{gen_id}/attempts"
    assert set(paths[collection]) == {"get", "post"}
    assert "201" in paths[collection]["post"]["responses"]
    assert set(paths[f"{collection}/{{attempt_id}}"]) == {"get"}


def test_get_attempt_wrong_generation_and_course_not_found(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    _register_course(tmp_path=tmp_path, key="altro")
    courses_dir = _store(tmp_path=tmp_path).courses_dir
    generation = make_generation(courses_dir=courses_dir, course_id=course_id)
    attempt = create_attempt(
        courses_dir=courses_dir, course_id=course_id, generation=generation
    )
    assert (
        client.get(url=f"{make_url(generation=generation)}/{attempt.id}").status_code
        == 200
    )
    wrong = replace(generation, id=str(uuid4()))
    assert (
        client.get(url=f"{make_url(generation=wrong)}/{attempt.id}").status_code == 404
    )
    assert (
        client.get(
            url=f"{make_url(generation=generation, key='altro')}/{attempt.id}"
        ).status_code
        == 404
    )


def test_get_attempt_invalid_ids_and_page_rejected(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    generation = make_generation(
        courses_dir=_store(tmp_path=tmp_path).courses_dir, course_id=course_id
    )
    assert (
        client.get(url=f"{make_url(generation=generation)}/invalid").status_code == 404
    )
    assert (
        client.get(url=make_url(generation=generation), params={"page": 0}).status_code
        == 422
    )
    assert (
        client.post(
            url="/api/v1/courses/fisica/generations/invalid/attempts"
        ).status_code
        == 404
    )
    assert (
        client.post(
            url=make_url(generation=replace(generation, id=str(uuid4())))
        ).status_code
        == 404
    )


def test_get_attempts_empty_page_has_meta(client: TestClient, tmp_path: Path) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    generation = make_generation(
        courses_dir=_store(tmp_path=tmp_path).courses_dir, course_id=course_id
    )
    response = client.get(url=make_url(generation=generation))
    assert response.status_code == 200
    assert response.json() == {
        "data": [],
        "meta": {"page": 1, "per_page": 20, "total": 0, "total_pages": 0},
    }

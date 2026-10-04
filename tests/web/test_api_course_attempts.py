from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from generation_api_fixtures import _register_course, _store, client
from test_api_practice import make_url
from test_practice_store import make_generation

from sbobina.generation_models import GenerationFormat
from sbobina.grading_models import CoveredPoint, Judgement, JudgementOutcome
from sbobina.practice_models import AnswerStatus, OpenAnswer
from sbobina.web.practice_store import create_attempt, practice_dir, save_attempt

__all__ = ["client"]
URL = "/api/v1/courses/fisica/attempts"


def attempt_url(tmp_path: Path) -> str:
    course_id = _register_course(tmp_path=tmp_path)
    courses_dir = _store(tmp_path=tmp_path).courses_dir
    generation = make_generation(courses_dir=courses_dir, course_id=course_id)
    attempt = create_attempt(
        courses_dir=courses_dir, course_id=course_id, generation=generation
    )
    return f"{make_url(generation=generation)}/{attempt.id}"


def test_course_attempts_empty_course_has_meta(
    client: TestClient, tmp_path: Path
) -> None:
    _register_course(tmp_path=tmp_path)

    response = client.get(url=URL)

    assert response.status_code == 200
    assert response.json() == {
        "data": [],
        "meta": {
            "page": 1,
            "per_page": 20,
            "total": 0,
            "total_pages": 0,
            "unavailable_attempts": [],
        },
    }


def test_course_attempts_summarise_progress_and_final_score(
    client: TestClient, tmp_path: Path
) -> None:
    url = attempt_url(tmp_path=tmp_path)
    client.post(url=f"{url}/answers/0", json={"choice": 0})
    client.post(url=f"{url}/answers/1", json={"choice": 2})

    response = client.get(url=URL)

    assert response.status_code == 200
    [summary] = response.json()["data"]
    attempt_id = url.rsplit("/", 1)[1]
    assert summary["id"] == attempt_id
    assert summary["generation_id"] == url.split("/")[-3]
    assert summary["format"] == "multiple_choice"
    assert (summary["answered"], summary["total"]) == (2, 2)
    assert (summary["score"], summary["pending"]) == (1.0, 0)
    assert summary["href"] == f"/corsi/fisica/esercitazioni/{attempt_id}"
    assert "questions" not in summary


def test_course_attempts_does_not_shadow_generation_attempts(
    client: TestClient, tmp_path: Path
) -> None:
    # Both routes use {key:path}: the course-level one must not swallow
    # /courses/<key>/generations/<gen>/attempts.
    url = attempt_url(tmp_path=tmp_path)
    collection = url.rsplit("/", 1)[0]

    response = client.get(url=collection)

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [url.rsplit("/", 1)[1]]
    assert "questions" in response.json()["data"][0]


def test_course_attempts_unreadable_file_is_reported(
    client: TestClient, tmp_path: Path
) -> None:
    url = attempt_url(tmp_path=tmp_path)
    courses_dir = _store(tmp_path=tmp_path).courses_dir
    course_id = next(courses_dir.glob("*/course.json")).parent.name
    bad_id = str(uuid4())
    (
        practice_dir(courses_dir=courses_dir, course_id=course_id) / f"{bad_id}.json"
    ).write_text("{", encoding="utf-8")

    response = client.get(url=URL)

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [url.rsplit("/", 1)[1]]
    assert response.json()["meta"]["unavailable_attempts"] == [bad_id]


def test_course_attempts_other_course_not_listed(
    client: TestClient, tmp_path: Path
) -> None:
    attempt_url(tmp_path=tmp_path)
    _register_course(tmp_path=tmp_path, key="chimica")

    assert len(client.get(url=URL).json()["data"]) == 1
    assert client.get(url=URL.replace("fisica", "chimica")).json()["data"] == []


def test_course_attempts_judge_suggestion_is_pending_self_grade_scores(
    client: TestClient, tmp_path: Path
) -> None:
    # U2: a judgement without the student's own grade is a suggestion, so it
    # is pending and stays out of the score; a self-grade counts.
    course_id = _register_course(tmp_path=tmp_path)
    courses_dir = _store(tmp_path=tmp_path).courses_dir
    generation = make_generation(courses_dir=courses_dir, course_id=course_id)
    questions = tuple(
        replace(question, options=(), correct_index=None, solution="Punto")
        for question in generation.questions
    )
    generation = replace(generation, format=GenerationFormat.OPEN, questions=questions)
    attempt = create_attempt(
        courses_dir=courses_dir, course_id=course_id, generation=generation
    )
    judgement = Judgement(
        covered_points=(CoveredPoint(point="Punto", evidence="tre parole qui"),),
        missing_points=(),
        errors=(),
    )
    answers = (
        OpenAnswer(
            answer_id=str(uuid4()),
            question_index=0,
            text="Risposta",
            status=AnswerStatus.GRADED,
            judgement=judgement,
        ),
        OpenAnswer(
            answer_id=str(uuid4()),
            question_index=1,
            text="Risposta",
            status=AnswerStatus.SELF_GRADED,
            self_grade=JudgementOutcome.PARTIAL,
            judgement=judgement,
        ),
    )
    save_attempt(
        courses_dir=courses_dir,
        course_id=course_id,
        attempt=replace(attempt, answers=answers),
    )

    [summary] = client.get(url=URL).json()["data"]

    assert (summary["answered"], summary["pending"]) == (2, 1)
    assert summary["score"] == 0.5

"""Course-wide list of practice attempts for the course detail (T051).

A summary per attempt, not its questions: the page links to the practice
page, which loads the full attempt. Registered after the generation routes,
since `{key:path}` would otherwise swallow `/generations/<gen>/attempts`.
"""

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder

from sbobina.practice_models import Answer, MultipleChoiceAnswer, PracticeAttempt
from sbobina.web.course_dependencies import ListedCourse, Services
from sbobina.web.pagination import Page, page_bounds, page_meta
from sbobina.web.practice_payloads import OUTCOME_SCORES, answer_outcome
from sbobina.web.practice_store import list_attempts

router = APIRouter(prefix="/api/v1/courses/{key:path}/attempts")


def final_answers(attempt: PracticeAttempt) -> list[Answer]:
    """Answers with a final outcome: multiple choice or the student's grade.

    A judge verdict without the student's own grade is a suggestion (U2), so
    that answer counts as pending, not in the score.
    """
    return [
        answer
        for answer in attempt.answers
        if isinstance(answer, MultipleChoiceAnswer) or answer.self_grade is not None
    ]


def attempt_summary(attempt: PracticeAttempt, key: str) -> dict[str, Any]:
    final = final_answers(attempt=attempt)
    score = sum(
        OUTCOME_SCORES[outcome]
        for answer in final
        if (outcome := answer_outcome(attempt=attempt, answer=answer)) is not None
    )
    payload: dict[str, Any] = jsonable_encoder(
        obj={
            "id": attempt.id,
            "generation_id": attempt.generation_id,
            "format": attempt.format,
            "status": attempt.status,
            "created_at": attempt.created_at,
            "updated_at": attempt.updated_at,
            "answered": len(attempt.answers),
            "total": len(attempt.questions),
            "score": score,
            "pending": len(attempt.answers) - len(final),
            "href": f"/corsi/{quote(string=key, safe='')}/esercitazioni/{attempt.id}",
        }
    )
    return payload


@router.get("")
def get_course_attempts(
    course: ListedCourse, services: Services, query: Page
) -> dict[str, Any]:
    if course is None:
        return {
            "data": [],
            "meta": {**page_meta(total=0, query=query), "unavailable_attempts": []},
        }
    scan = list_attempts(courses_dir=services.store.courses_dir, course_id=course.id)
    attempts = [attempt for attempt in scan.attempts if attempt.course_id == course.id]
    return {
        "data": [
            attempt_summary(attempt=attempt, key=course.key)
            for attempt in attempts[page_bounds(query=query)]
        ],
        "meta": {
            **page_meta(total=len(attempts), query=query),
            "unavailable_attempts": list(scan.unavailable_ids),
        },
    }

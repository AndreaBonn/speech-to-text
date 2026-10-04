from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from sbobina.grading_models import JudgementOutcome
from sbobina.web.api_practice import (
    GradingServices,
    _validate_generation_id,
    text_payload,
)
from sbobina.web.course_dependencies import Course
from sbobina.web.practice_answers import AnswerTarget
from sbobina.web.practice_grading import grading_mode
from sbobina.web.practice_text_answers import (
    AnswerLocation,
    retry_grade,
    submit_self_grade,
)

router = APIRouter(prefix="/api/v1/courses/{key:path}/generations/{gen_id}/attempts")


class SelfGradeSubmission(BaseModel):
    outcome: JudgementOutcome


@router.post("/{attempt_id}/answers/{question_index}/grade")
def grade_submitted_answer(
    target: Annotated[AnswerTarget, Depends()],
    course: Course,
    services: GradingServices,
) -> dict[str, Any]:
    _validate_generation_id(gen_id=target.gen_id)
    location = AnswerLocation(
        courses_dir=services.store.courses_dir, course_id=course.id, target=target
    )
    attempt = retry_grade(location=location, services=services)
    return {
        "data": text_payload(
            attempt=attempt,
            index=target.question_index,
            mode=grading_mode(settings=services.settings),
        )
    }


@router.post("/{attempt_id}/answers/{question_index}/self-grade")
def self_grade_answer(
    target: Annotated[AnswerTarget, Depends()],
    body: SelfGradeSubmission,
    course: Course,
    services: GradingServices,
) -> dict[str, Any]:
    _validate_generation_id(gen_id=target.gen_id)
    location = AnswerLocation(
        courses_dir=services.store.courses_dir, course_id=course.id, target=target
    )
    attempt = submit_self_grade(location=location, outcome=body.outcome)
    return {
        "data": text_payload(
            attempt=attempt,
            index=target.question_index,
            mode=grading_mode(settings=services.settings),
        )
    }

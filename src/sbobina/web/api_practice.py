"""Practice creation and per-question disclosure after submission."""

from typing import Any

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder

from sbobina.generation_models import GenerationQuestion, GenerationStatus
from sbobina.practice_models import AnswerStatus, PracticeAttempt, require_uuid4
from sbobina.web.course_dependencies import Course, Services
from sbobina.web.errors import ConflictError, NotFoundError, ValidationError
from sbobina.web.generation_store import load_generation
from sbobina.web.pagination import Page, page_bounds, page_meta
from sbobina.web.practice_store import create_attempt, list_attempts, load_attempt

router = APIRouter(prefix="/api/v1/courses/{key:path}/generations/{gen_id}/attempts")


def _validate_generation_id(gen_id: str) -> None:
    try:
        require_uuid4(value=gen_id, field="generation_id")
    except ValueError as error:
        raise NotFoundError(entity="Generazione", id=gen_id) from error


def _question_payload(
    question: GenerationQuestion, is_submitted: bool
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "question": question.question,
        "options": list(question.options),
    }
    if is_submitted:
        payload.update(
            solution=question.solution,
            correct_index=question.correct_index,
            citations=jsonable_encoder(obj=question.citations),
        )
    return payload


def _attempt_payload(attempt: PracticeAttempt) -> dict[str, Any]:
    submitted = {
        answer.question_index
        for answer in attempt.answers
        if answer.status
        in (AnswerStatus.UNGRADED, AnswerStatus.GRADED, AnswerStatus.SELF_GRADED)
    }
    payload: dict[str, Any] = jsonable_encoder(
        obj={
            "id": attempt.id,
            "course_id": attempt.course_id,
            "generation_id": attempt.generation_id,
            "format": attempt.format,
            "status": attempt.status,
            "created_at": attempt.created_at,
            "updated_at": attempt.updated_at,
            "answers": attempt.answers,
            "questions": [
                _question_payload(question=question, is_submitted=index in submitted)
                for index, question in enumerate(attempt.questions)
            ],
        }
    )
    return payload


@router.post("", status_code=201)
def add_attempt(gen_id: str, course: Course, services: Services) -> dict[str, Any]:
    _validate_generation_id(gen_id=gen_id)
    generation = load_generation(
        courses_dir=services.store.courses_dir,
        course_id=course.id,
        gen_id=gen_id,
    )
    if generation.status == GenerationStatus.FAILED:
        raise ConflictError(
            message="La generazione è fallita.", code="GENERATION_FAILED"
        )
    try:
        attempt = create_attempt(
            courses_dir=services.store.courses_dir,
            course_id=course.id,
            generation=generation,
        )
    except ValueError as error:
        raise ValidationError(
            message="Serve una generazione completata di domande, non un riassunto."
        ) from error
    return {"data": _attempt_payload(attempt=attempt)}


@router.get("/{attempt_id}")
def get_attempt(
    gen_id: str, attempt_id: str, course: Course, services: Services
) -> dict[str, Any]:
    _validate_generation_id(gen_id=gen_id)
    attempt = load_attempt(
        courses_dir=services.store.courses_dir,
        course_id=course.id,
        attempt_id=attempt_id,
    )
    if attempt.generation_id != gen_id or attempt.course_id != course.id:
        raise NotFoundError(entity="Tentativo", id=attempt_id)
    return {"data": _attempt_payload(attempt=attempt)}


@router.get("")
def get_attempts(
    gen_id: str, course: Course, services: Services, query: Page
) -> dict[str, Any]:
    _validate_generation_id(gen_id=gen_id)
    attempts = [
        attempt
        for attempt in list_attempts(
            courses_dir=services.store.courses_dir, course_id=course.id
        )
        if attempt.generation_id == gen_id and attempt.course_id == course.id
    ]
    return {
        "data": [
            _attempt_payload(attempt=attempt)
            for attempt in attempts[page_bounds(query=query)]
        ],
        "meta": page_meta(total=len(attempts), query=query),
    }

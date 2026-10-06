"""Practice creation and per-question disclosure after submission."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field

from sbobina.course_registry import CourseRecord
from sbobina.generation_models import (
    EXPECTED_OPTION_COUNT,
    GenerationQuestion,
    GenerationStatus,
)
from sbobina.practice_models import AnswerStatus, PracticeAttempt, require_uuid4
from sbobina.runtime_config import runtime_settings
from sbobina.web.api_chat import _chat_client
from sbobina.web.course_dependencies import Course, Services
from sbobina.web.errors import ConflictError, NotFoundError, ValidationError
from sbobina.web.generation_citations_api import CitationContext
from sbobina.web.generation_store import load_generation
from sbobina.web.job_store import JobStore
from sbobina.web.pagination import Page, page_bounds, page_meta
from sbobina.web.practice_answers import AnswerTarget, submit_choice
from sbobina.web.practice_citations import practice_citation
from sbobina.web.practice_grading import PracticeServices, grading_mode
from sbobina.web.practice_payloads import answer_payload
from sbobina.web.practice_store import create_attempt, list_attempts, load_attempt
from sbobina.web.practice_text_answers import (
    AnswerLocation,
    TextSubmission,
    submit_text,
    text_answer,
)

router = APIRouter(prefix="/api/v1/courses/{key:path}/generations/{gen_id}/attempts")


def _grading_services(request: Request) -> PracticeServices:
    settings = runtime_settings(settings=request.app.state.settings)
    return PracticeServices(
        store=request.app.state.job_store,
        settings=settings,
        arbiter=request.app.state.gpu_arbiter,
        chat=_chat_client(request=request),
        guard_whole_client=settings.llm_engine == "local",
    )


GradingServices = Annotated[PracticeServices, Depends(_grading_services)]


class ChoiceSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    choice: int = Field(strict=True, ge=0, lt=EXPECTED_OPTION_COUNT)


def _text_answer(
    target: AnswerTarget,
    body: TextSubmission,
    course: CourseRecord,
    services: PracticeServices,
) -> dict[str, Any]:
    location = AnswerLocation(
        courses_dir=services.store.courses_dir, course_id=course.id, target=target
    )
    attempt = submit_text(location=location, body=body, services=services)
    return text_payload(
        attempt=attempt,
        index=target.question_index,
        mode=grading_mode(settings=services.settings),
        context=citation_context(store=services.store, course=course, attempt=attempt),
    )


@router.post("/{attempt_id}/answers/{question_index}")
def add_choice_answer(
    target: Annotated[AnswerTarget, Depends()],
    body: ChoiceSubmission | TextSubmission,
    course: Course,
    services: GradingServices,
) -> dict[str, Any]:
    _validate_generation_id(gen_id=target.gen_id)
    if isinstance(body, TextSubmission):
        return {
            "data": _text_answer(
                target=target, body=body, course=course, services=services
            )
        }
    attempt = submit_choice(
        courses_dir=services.store.courses_dir,
        course_id=course.id,
        target=target,
        choice=body.choice,
    )
    return {
        "data": choice_payload(
            attempt=attempt,
            index=target.question_index,
            context=citation_context(
                store=services.store, course=course, attempt=attempt
            ),
        )
    }


def citation_context(
    store: JobStore, course: CourseRecord, attempt: PracticeAttempt
) -> CitationContext:
    return CitationContext(
        courses_dir=store.courses_dir,
        store=store,
        course_id=course.id,
        key=course.key,
        sources=attempt.sources,
    )


def choice_payload(
    attempt: PracticeAttempt, index: int, context: CitationContext
) -> dict[str, Any]:
    answer = next(item for item in attempt.answers if item.question_index == index)
    return {
        **_question_payload(
            question=attempt.questions[index], is_submitted=True, context=context
        ),
        **answer_payload(attempt=attempt, answer=answer),
    }


def text_payload(
    attempt: PracticeAttempt, index: int, mode: str, context: CitationContext
) -> dict[str, Any]:
    return {
        **_question_payload(
            question=attempt.questions[index], is_submitted=True, context=context
        ),
        **answer_payload(
            attempt=attempt, answer=text_answer(attempt=attempt, question_index=index)
        ),
        "grading_mode": mode,
    }


def _validate_generation_id(gen_id: str) -> None:
    try:
        require_uuid4(value=gen_id, field="generation_id")
    except ValueError as error:
        raise NotFoundError(entity="Generazione", id=gen_id) from error


def _question_payload(
    question: GenerationQuestion, is_submitted: bool, context: CitationContext
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "question": question.question,
        "options": list(question.options),
    }
    if is_submitted:
        payload.update(
            solution=question.solution,
            correct_index=question.correct_index,
            citations=[
                practice_citation(citation=citation, context=context)
                for citation in question.citations
            ],
        )
    return payload


def _submitted_indexes(attempt: PracticeAttempt) -> set[int]:
    return {
        answer.question_index
        for answer in attempt.answers
        if answer.status
        in (AnswerStatus.UNGRADED, AnswerStatus.GRADED, AnswerStatus.SELF_GRADED)
    }


def _attempt_payload(
    attempt: PracticeAttempt, context: CitationContext
) -> dict[str, Any]:
    submitted = _submitted_indexes(attempt=attempt)
    payload: dict[str, Any] = jsonable_encoder(
        obj={
            "id": attempt.id,
            "course_id": attempt.course_id,
            "generation_id": attempt.generation_id,
            "format": attempt.format,
            "status": attempt.status,
            "created_at": attempt.created_at,
            "updated_at": attempt.updated_at,
            "answers": [
                answer_payload(attempt=attempt, answer=answer)
                for answer in attempt.answers
            ],
            "questions": [
                _question_payload(
                    question=question,
                    is_submitted=index in submitted,
                    context=context,
                )
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
    return {
        "data": _attempt_payload(
            attempt=attempt,
            context=citation_context(
                store=services.store, course=course, attempt=attempt
            ),
        )
    }


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
    return {
        "data": _attempt_payload(
            attempt=attempt,
            context=citation_context(
                store=services.store, course=course, attempt=attempt
            ),
        )
    }


@router.get("")
def get_attempts(
    gen_id: str, course: Course, services: Services, query: Page
) -> dict[str, Any]:
    _validate_generation_id(gen_id=gen_id)
    scan = list_attempts(courses_dir=services.store.courses_dir, course_id=course.id)
    attempts = [
        attempt
        for attempt in scan.attempts
        if attempt.generation_id == gen_id and attempt.course_id == course.id
    ]
    return {
        "data": [
            _attempt_payload(
                attempt=attempt,
                context=citation_context(
                    store=services.store, course=course, attempt=attempt
                ),
            )
            for attempt in attempts[page_bounds(query=query)]
        ],
        "meta": {
            **page_meta(total=len(attempts), query=query),
            "unavailable_attempts": list(scan.unavailable_ids),
        },
    }

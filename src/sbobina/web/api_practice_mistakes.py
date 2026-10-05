from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from sbobina.card_models import CardDraft, GenerationAnchor
from sbobina.web.card_store import create_card_result
from sbobina.web.course_dependencies import (
    Course,
    ListedCourse,
    Services,
    card_payload,
)
from sbobina.web.errors import NotFoundError, ValidationError
from sbobina.web.generation_citations_api import CitationContext
from sbobina.web.pagination import Page, page_bounds, page_meta
from sbobina.web.path_locks import lock_for
from sbobina.web.practice_citations import practice_citation
from sbobina.web.practice_mistakes import (
    MISTAKE_OUTCOMES,
    PracticeMistake,
    latest_mistakes,
)
from sbobina.web.practice_payloads import answer_outcome, answer_payload
from sbobina.web.practice_store import list_attempts, load_attempt, practice_path

router = APIRouter(prefix="/api/v1/courses/{key:path}/mistakes")
PRACTICE_CARD_SOURCE = "practice"


@dataclass(frozen=True, kw_only=True)
class MistakeTarget:
    attempt_id: str
    question_index: int


def mistake_payload(item: PracticeMistake, context: CitationContext) -> dict[str, Any]:
    question = item.attempt.questions[item.answer.question_index]
    return {
        **answer_payload(attempt=item.attempt, answer=item.answer),
        "attempt_id": item.attempt.id,
        "generation_id": item.attempt.generation_id,
        "question": question.question,
        "solution": question.solution,
        "citations": [
            practice_citation(citation=citation, context=context)
            for citation in question.citations
        ],
    }


@router.get("")
def get_mistakes(
    course: ListedCourse, services: Services, query: Page
) -> dict[str, Any]:
    if course is None:
        return {
            "data": [],
            "meta": {**page_meta(total=0, query=query), "unavailable_attempts": []},
        }
    scan = list_attempts(courses_dir=services.store.courses_dir, course_id=course.id)
    mistakes = latest_mistakes(attempts=scan.attempts, course_id=course.id)
    return {
        "data": [
            mistake_payload(
                item=item,
                context=CitationContext(
                    courses_dir=services.store.courses_dir,
                    store=services.store,
                    course_id=course.id,
                    key=course.key,
                    sources=item.attempt.sources,
                ),
            )
            for item in mistakes[page_bounds(query=query)]
        ],
        "meta": {
            **page_meta(total=len(mistakes), query=query),
            "unavailable_attempts": list(scan.unavailable_ids),
        },
    }


def mistake_draft(item: PracticeMistake) -> CardDraft:
    index = item.answer.question_index
    question = item.attempt.questions[index]
    try:
        return CardDraft(
            front=question.question,
            back=question.solution,
            source=PRACTICE_CARD_SOURCE,
            anchor=GenerationAnchor(
                generation_id=item.attempt.generation_id, question_index=index
            ),
            dedup_key=f"practice:{item.attempt.id}:{index}",
        )
    except ValueError as error:
        raise ValidationError(message=str(error)) from error


def find_mistake(
    target: MistakeTarget, course: Course, services: Services
) -> PracticeMistake:
    attempt = load_attempt(
        courses_dir=services.store.courses_dir,
        course_id=course.id,
        attempt_id=target.attempt_id,
    )
    answer = next(
        (
            answer
            for answer in attempt.answers
            if answer.question_index == target.question_index
        ),
        None,
    )
    if (
        attempt.course_id != course.id
        or answer is None
        or answer_outcome(attempt=attempt, answer=answer) not in MISTAKE_OUTCOMES
    ):
        raise NotFoundError(entity="Errore", id=str(target.question_index))
    return PracticeMistake(attempt=attempt, answer=answer)


@router.post("/{attempt_id}/{question_index}/card", status_code=201)
def add_mistake_card(
    target: Annotated[MistakeTarget, Depends()],
    course: Course,
    services: Services,
) -> JSONResponse:
    try:
        path = practice_path(
            courses_dir=services.store.courses_dir,
            course_id=course.id,
            attempt_id=target.attempt_id,
        )
    except ValueError as error:
        raise NotFoundError(entity="Tentativo", id=target.attempt_id) from error
    with lock_for(path=path.with_suffix(".submission")):
        item = find_mistake(target=target, course=course, services=services)
        card, created = create_card_result(
            courses_dir=services.store.courses_dir,
            course_id=course.id,
            now=services.now,
            draft=mistake_draft(item=item),
        )
    return JSONResponse(
        status_code=201 if created else 200,
        content={"data": card_payload(card=card, course=course, services=services)},
    )

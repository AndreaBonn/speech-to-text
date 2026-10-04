from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, field_validator

from sbobina.card_anchors import resolve_anchor
from sbobina.card_models import Card, CardDraft
from sbobina.concept_cards import concept_cards
from sbobina.course_registry import (
    CourseRecord,
    find_by_key,
    get_or_create,
    iter_courses,
)
from sbobina.courses import course_key, effective_course
from sbobina.flashcard_scheduler import Rating, Scheduler
from sbobina.review_queue import due_today
from sbobina.settings import Settings
from sbobina.study_render import load_study
from sbobina.time_guards import require_aware
from sbobina.web.api_files import existing_file, find_job
from sbobina.web.api_study import STUDY_FILE, _load_current_transcript
from sbobina.web.card_store import ReviewRequest, create_card, load_cards, record_review
from sbobina.web.errors import ConflictError, NotFoundError, ValidationError
from sbobina.web.job_store import JobStore
from sbobina.web.path_locks import lock_for

router = APIRouter(prefix="/api/v1")
CONCEPT_SOURCE = "concept"
DEFAULT_PAGE = 1
DEFAULT_PER_PAGE = 20
NUMERIC_RATINGS = {1: Rating.AGAIN, 2: Rating.HARD, 3: Rating.GOOD, 4: Rating.EASY}


def review_clock() -> datetime:
    return datetime.now(tz=UTC)


def review_scheduler() -> Scheduler:
    return Scheduler(enable_fuzzing=True)


@dataclass(frozen=True, kw_only=True)
class ReviewServices:
    store: JobStore
    settings: Settings
    now: datetime
    scheduler: Scheduler


def _services(
    request: Request,
    now: Annotated[datetime, Depends(review_clock)],
    scheduler: Annotated[Scheduler, Depends(review_scheduler)],
) -> ReviewServices:
    return ReviewServices(
        store=request.app.state.job_store,
        settings=request.app.state.settings,
        now=now,
        scheduler=scheduler,
    )


Services = Annotated[ReviewServices, Depends(_services)]


def _course(key: str, services: Services) -> CourseRecord:
    course = find_by_key(
        courses_dir=services.store.courses_dir, key=course_key(label=key)
    )
    if course is None:
        raise NotFoundError(entity="Corso", id=key)
    return course


Course = Annotated[CourseRecord, Depends(_course)]


@dataclass(frozen=True, kw_only=True)
class ReviewPage:
    page: int
    per_page: int


def _query(
    page: Annotated[int, Query(ge=1)] = DEFAULT_PAGE,
    per_page: Annotated[int, Query(ge=1)] = DEFAULT_PER_PAGE,
) -> ReviewPage:
    return ReviewPage(page=page, per_page=per_page)


Page = Annotated[ReviewPage, Depends(_query)]


class ReviewBody(BaseModel):
    model_config = ConfigDict(frozen=True)
    rating: Rating
    observed_due: datetime | None

    @field_validator("rating", mode="before")
    @classmethod
    def validate_rating(cls, value: object) -> Rating:
        if type(value) is int and value in NUMERIC_RATINGS:
            return NUMERIC_RATINGS[value]
        if isinstance(value, str):
            try:
                return Rating(value=value)
            except ValueError:
                pass
        raise ValueError(
            "Il voto deve essere 1–4 oppure Di nuovo, Difficile, Bene o Facile"
        )

    @field_validator("observed_due")
    @classmethod
    def validate_due(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            require_aware(value=value, field="observed_due")
        return value


def _queue(course_id: str, services: ReviewServices) -> tuple[Card, ...]:
    return due_today(
        cards=load_cards(courses_dir=services.store.courses_dir, course_id=course_id),
        now=services.now,
        new_limit=services.settings.review_new_per_day,
    )


def _card_payload(
    card: Card, course: CourseRecord, services: ReviewServices
) -> dict[str, Any]:
    resolution = resolve_anchor(
        anchor=card.anchor, store=services.store, course_id=course.id, key=course.key
    )
    payload: dict[str, Any] = jsonable_encoder(obj=card)
    return {**payload, "anchor_resolution": jsonable_encoder(obj=resolution)}


def _page_bounds(query: ReviewPage) -> slice:
    start = (query.page - 1) * query.per_page
    return slice(start, start + query.per_page)


def _page_meta(total: int, query: ReviewPage) -> dict[str, int]:
    return {
        "page": query.page,
        "per_page": query.per_page,
        "total": total,
        "total_pages": (total + query.per_page - 1) // query.per_page,
    }


@router.get("/courses/{key:path}/review/today")
def today(course: Course, services: Services, query: Page) -> dict[str, Any]:
    cards = _queue(course_id=course.id, services=services)
    # Anchors are resolved only for the cards on this page: resolution reads files.
    return {
        "data": [
            _card_payload(card=card, course=course, services=services)
            for card in cards[_page_bounds(query=query)]
        ],
        "meta": _page_meta(total=len(cards), query=query),
    }


@router.post("/courses/{key:path}/cards/{card_id}/review")
def review_card(
    card_id: str, body: ReviewBody, course: Course, services: Services
) -> dict[str, Any]:
    event = record_review(
        courses_dir=services.store.courses_dir,
        course_id=course.id,
        request=ReviewRequest(
            card_id=card_id,
            rating=body.rating,
            observed_due=body.observed_due,
            now=services.now,
        ),
        scheduler=services.scheduler,
    )
    return {"data": jsonable_encoder(obj=event)}


@router.get("/review/summary")
def summary(services: Services, query: Page) -> dict[str, Any]:
    courses = sorted(
        iter_courses(courses_dir=services.store.courses_dir),
        key=lambda course: course.key,
    )
    return {
        "data": [
            {
                "course_key": course.key,
                "label": course.label,
                "due": len(_queue(course_id=course.id, services=services)),
            }
            for course in courses[_page_bounds(query=query)]
        ],
        "meta": _page_meta(total=len(courses), query=query),
    }


def _import_cards(
    course_id: str, drafts: tuple[CardDraft, ...], services: ReviewServices
) -> int:
    directory = services.store.courses_dir / course_id
    # Separate from the store's file locks: serialize batch accounting without reentry.
    with lock_for(path=directory / "concept-import"):
        known = {
            card.id
            for card in load_cards(
                courses_dir=services.store.courses_dir, course_id=course_id
            )
        }
        created = 0
        for draft in drafts:
            card = create_card(
                courses_dir=services.store.courses_dir,
                course_id=course_id,
                draft=draft,
                now=services.now,
            )
            created += card.id not in known
            known.add(card.id)
        return created


def _concept_drafts(directory: Path, job_id: str) -> tuple[CardDraft, ...]:
    path = existing_file(directory=directory, name=STUDY_FILE)
    transcript, revision = _load_current_transcript(directory=directory)
    try:
        study = load_study(path=path, transcript=transcript)
        return concept_cards(
            result=study.result,
            job_id=job_id,
            revision=revision,
            source=CONCEPT_SOURCE,
        )
    except ValueError as error:
        raise ValidationError(
            message="Materiale di studio non valido per le carte"
        ) from error


@router.post("/jobs/{job_id}/cards/from-concepts", status_code=201)
def from_concepts(request: Request, job_id: str, services: Services) -> dict[str, Any]:
    record, directory = find_job(request=request, job_id=job_id)
    label = effective_course(
        course=services.store.read_meta(job_id=str(record.id)).course,
        subject=record.config.subject,
    )
    if label is None:
        raise ConflictError(message="Seleziona un corso", code="COURSE_REQUIRED")
    drafts = _concept_drafts(directory=directory, job_id=str(record.id))
    course = get_or_create(
        courses_dir=services.store.courses_dir, key=course_key(label=label), label=label
    )
    return {
        "data": {
            "created": _import_cards(
                course_id=course.id, drafts=drafts, services=services
            )
        }
    }

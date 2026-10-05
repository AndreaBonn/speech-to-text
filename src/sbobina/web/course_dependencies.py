from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.encoders import jsonable_encoder

from sbobina.card_anchors import resolve_anchor
from sbobina.card_models import Card
from sbobina.course_registry import CourseRecord, find_by_key
from sbobina.courses import course_key
from sbobina.flashcard_scheduler import Scheduler
from sbobina.settings import Settings
from sbobina.web.course_retrieval import course_scope
from sbobina.web.errors import NotFoundError
from sbobina.web.job_store import JobStore


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


def _listed_course(key: str, services: Services) -> CourseRecord | None:
    """The registered course, or None for a course known only by its lectures.

    The registry record appears with the first document, card or rename; until
    then the course has nothing to list but exists, so lists answer empty.
    """
    normalized = course_key(label=key)
    course = find_by_key(courses_dir=services.store.courses_dir, key=normalized)
    if (
        course is None
        and not course_scope(store=services.store, key=normalized).job_ids
    ):
        raise NotFoundError(entity="Corso", id=key)
    return course


ListedCourse = Annotated[CourseRecord | None, Depends(_listed_course)]


def card_payload(
    card: Card, course: CourseRecord, services: ReviewServices
) -> dict[str, Any]:
    resolution = resolve_anchor(
        anchor=card.anchor, store=services.store, course_id=course.id, key=course.key
    )
    payload: dict[str, Any] = jsonable_encoder(obj=card)
    return {**payload, "anchor_resolution": jsonable_encoder(obj=resolution)}

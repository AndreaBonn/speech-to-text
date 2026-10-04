from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, field_validator

from sbobina.card_anchors import resolve_anchor
from sbobina.card_models import (
    Anchor,
    CardDeleted,
    CardDraft,
    CardEdited,
    LectureAnchor,
    validate_card_text,
)
from sbobina.course_registry import CourseRecord
from sbobina.web.card_store import append_card_event, create_card, load_cards
from sbobina.web.course_dependencies import (
    Course,
    ReviewServices,
    Services,
    card_payload,
)
from sbobina.web.course_retrieval import course_scope, lecture_revision
from sbobina.web.errors import ConflictError, NotFoundError
from sbobina.web.pagination import Page, page_bounds, page_meta

router = APIRouter(prefix="/api/v1")
MANUAL_SOURCE = "manual"


class CardTextBody(BaseModel):
    model_config = ConfigDict(frozen=True)
    front: str
    back: str

    @field_validator("front")
    @classmethod
    def validate_front(cls, value: str) -> str:
        validate_card_text(front=value, back=None)
        return value

    @field_validator("back")
    @classmethod
    def validate_back(cls, value: str) -> str:
        validate_card_text(front=None, back=value)
        return value


class CreateCardBody(CardTextBody):
    anchor: Anchor


def _validate_lecture(
    anchor: LectureAnchor, course: CourseRecord, services: ReviewServices
) -> None:
    services.store.get(job_id=anchor.job_id)
    scope = course_scope(store=services.store, key=course.key)
    if anchor.job_id not in scope.job_ids:
        raise ConflictError(
            message="La lezione non appartiene a questo corso.",
            code="LECTURE_NOT_IN_COURSE",
        )
    try:
        revision = lecture_revision(store=services.store, job_id=anchor.job_id)
    except UnicodeError:
        revision = None
    if anchor.revision == revision:
        return
    resolution = resolve_anchor(
        anchor=anchor, store=services.store, course_id=course.id, key=course.key
    )
    if resolution.status not in {"ok", "moved"}:
        raise ConflictError(
            message="Il passaggio citato non esiste più in questa forma.",
            code="SOURCE_CHANGED",
        )


@router.post("/courses/{key:path}/cards", status_code=201)
def add_card(
    body: CreateCardBody, course: Course, services: Services
) -> dict[str, Any]:
    if isinstance(body.anchor, LectureAnchor):
        _validate_lecture(anchor=body.anchor, course=course, services=services)
    card = create_card(
        courses_dir=services.store.courses_dir,
        course_id=course.id,
        draft=CardDraft(
            front=body.front,
            back=body.back,
            source=MANUAL_SOURCE,
            anchor=body.anchor,
            dedup_key=None,
        ),
        now=services.now,
    )
    return {"data": card_payload(card=card, course=course, services=services)}


@router.patch("/courses/{key:path}/cards/{card_id}")
def edit_card(
    card_id: str, body: CardTextBody, course: Course, services: Services
) -> dict[str, Any]:
    append_card_event(
        courses_dir=services.store.courses_dir,
        course_id=course.id,
        event=CardEdited(
            card_id=card_id, occurred_at=services.now, front=body.front, back=body.back
        ),
    )
    cards = load_cards(courses_dir=services.store.courses_dir, course_id=course.id)
    for card in cards:
        if card.id == card_id:
            return {"data": card_payload(card=card, course=course, services=services)}
    raise NotFoundError(entity="Carta", id=card_id)


@router.get("/courses/{key:path}/cards")
def list_cards(course: Course, services: Services, query: Page) -> dict[str, Any]:
    cards = load_cards(courses_dir=services.store.courses_dir, course_id=course.id)
    return {
        "data": [
            card_payload(card=card, course=course, services=services)
            for card in cards[page_bounds(query=query)]
        ],
        "meta": page_meta(total=len(cards), query=query),
    }


@router.delete("/courses/{key:path}/cards/{card_id}", status_code=204)
def delete_card(card_id: str, course: Course, services: Services) -> Response:
    append_card_event(
        courses_dir=services.store.courses_dir,
        course_id=course.id,
        event=CardDeleted(card_id=card_id, occurred_at=services.now),
    )
    return Response(status_code=204)

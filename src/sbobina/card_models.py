"""Immutable card lifecycle records, review records and their in-memory view."""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter

from sbobina.flashcard_scheduler import FsrsState, Rating
from sbobina.time_guards import require_aware

MAX_CARD_TEXT_LENGTH = 2000
# Bounds the cost of re-tokenizing a quote on every relocation attempt
# (card_anchors._relocate calls locate_quote once per candidate segment).
MAX_QUOTE_CHARS = 2000


def validate_card_text(*, front: str | None, back: str | None) -> None:
    for label, text in (("fronte", front), ("retro", back)):
        if text is None:
            continue
        if not text.strip() or len(text) > MAX_CARD_TEXT_LENGTH:
            raise ValueError(
                f"Il {label} deve contenere da 1 a "
                f"{MAX_CARD_TEXT_LENGTH} caratteri e non può essere vuoto."
            )


def _require_uuid4(value: str, field: str) -> None:
    """Reject anything that is not a canonical UUID4, so an anchor id can never
    double as a path segment (``../x``) when resolvers join it onto a directory."""
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ValueError(f"{field} deve essere un UUID4 valido") from error
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError(f"{field} deve essere un UUID4 valido")


@dataclass(frozen=True, kw_only=True)
class LectureAnchor:
    job_id: str
    revision: str
    segment_index: int
    quote: str
    kind: Literal["lecture"] = "lecture"

    def __post_init__(self) -> None:
        _require_uuid4(self.job_id, "job_id")
        if not self.revision:
            raise ValueError("job_id e revision non possono essere vuoti")
        if self.segment_index < 0:
            raise ValueError("segment_index deve essere >= 0")
        if len(self.quote) > MAX_QUOTE_CHARS:
            raise ValueError(f"quote non può superare {MAX_QUOTE_CHARS} caratteri")
        if not self.quote.strip():
            raise ValueError("quote non può essere vuoto")


@dataclass(frozen=True, kw_only=True)
class DocumentAnchor:
    doc_id: str
    sha256: str
    page: int
    quote: str
    kind: Literal["document"] = "document"

    def __post_init__(self) -> None:
        _require_uuid4(self.doc_id, "doc_id")
        if not self.sha256:
            raise ValueError("doc_id e sha256 non possono essere vuoti")
        if self.page < 0:
            raise ValueError("page deve essere >= 0")
        if len(self.quote) > MAX_QUOTE_CHARS:
            raise ValueError(f"quote non può superare {MAX_QUOTE_CHARS} caratteri")
        if not self.quote.strip():
            raise ValueError("quote non può essere vuoto")


@dataclass(frozen=True, kw_only=True)
class GenerationAnchor:
    generation_id: str
    question_index: int
    kind: Literal["generation"] = "generation"

    def __post_init__(self) -> None:
        _require_uuid4(self.generation_id, "generation_id")
        if self.question_index < 0:
            raise ValueError("question_index deve essere >= 0")


type Anchor = Annotated[
    LectureAnchor | DocumentAnchor | GenerationAnchor, Field(discriminator="kind")
]


@dataclass(frozen=True, kw_only=True)
class CardDraft:
    front: str
    back: str
    source: str
    anchor: Anchor
    dedup_key: str | None = None

    def __post_init__(self) -> None:
        validate_card_text(front=self.front, back=self.back)


# Separate event types prevent unrelated lifecycle fields appearing together.
@dataclass(frozen=True, kw_only=True)
class CardCreated:
    card_id: str
    occurred_at: datetime
    front: str
    back: str
    source: str
    anchor: Anchor
    dedup_key: str | None = None
    kind: Literal["created"] = "created"

    def __post_init__(self) -> None:
        validate_card_text(front=self.front, back=self.back)
        require_aware(value=self.occurred_at, field="occurred_at")


@dataclass(frozen=True, kw_only=True)
class CardEdited:
    card_id: str
    occurred_at: datetime
    front: str
    back: str
    kind: Literal["edited"] = "edited"

    def __post_init__(self) -> None:
        validate_card_text(front=self.front, back=self.back)
        require_aware(value=self.occurred_at, field="occurred_at")


@dataclass(frozen=True, kw_only=True)
class CardSuspended:
    card_id: str
    occurred_at: datetime
    suspended: bool = True
    kind: Literal["suspended"] = "suspended"

    def __post_init__(self) -> None:
        require_aware(value=self.occurred_at, field="occurred_at")


@dataclass(frozen=True, kw_only=True)
class CardDeleted:
    card_id: str
    occurred_at: datetime
    kind: Literal["deleted"] = "deleted"

    def __post_init__(self) -> None:
        require_aware(value=self.occurred_at, field="occurred_at")


type CardEvent = Annotated[
    CardCreated | CardEdited | CardSuspended | CardDeleted, Field(discriminator="kind")
]


@dataclass(frozen=True, kw_only=True)
class ReviewEvent:
    card_id: str
    rating: Rating
    reviewed_at: datetime
    duration_ms: int | None
    fsrs: FsrsState

    def __post_init__(self) -> None:
        require_aware(value=self.reviewed_at, field="reviewed_at")
        if self.fsrs.due < self.reviewed_at:
            raise ValueError("due must not precede reviewed_at")


@dataclass(frozen=True, kw_only=True)
class Card:
    id: str
    front: str
    back: str
    source: str
    anchor: Anchor
    fsrs: FsrsState | None
    suspended: bool = False

    def __post_init__(self) -> None:
        validate_card_text(front=self.front, back=self.back)


CARD_EVENT_ADAPTER: TypeAdapter[CardEvent] = TypeAdapter(CardEvent)
REVIEW_ADAPTER = TypeAdapter(ReviewEvent)


def dump_card_event(event: CardEvent) -> str:
    return CARD_EVENT_ADAPTER.dump_json(event).decode("utf-8") + "\n"


def load_card_event(content: str) -> CardEvent:
    return CARD_EVENT_ADAPTER.validate_json(content)


def dump_review(event: ReviewEvent) -> str:
    return REVIEW_ADAPTER.dump_json(event).decode("utf-8") + "\n"


def load_review(content: str) -> ReviewEvent:
    return REVIEW_ADAPTER.validate_json(content)

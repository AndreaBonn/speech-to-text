"""Self-contained practice snapshots and submitted answers."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter

from sbobina.generation_models import GenerationFormat, GenerationQuestion
from sbobina.time_guards import require_aware


class PracticeStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    GRADED = "graded"


class AnswerStatus(StrEnum):
    UNGRADED = "ungraded"
    GRADED = "graded"
    SELF_GRADED = "self_graded"


def require_uuid4(value: str, field: str) -> None:
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ValueError(f"{field} must be a canonical UUID4") from error
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError(f"{field} must be a canonical UUID4")


@dataclass(frozen=True, kw_only=True)
class SubmittedAnswer:
    """Presence means submitted, including answers still awaiting grading."""

    answer_id: str
    question_index: int
    status: AnswerStatus = AnswerStatus.UNGRADED

    def __post_init__(self) -> None:
        require_uuid4(value=self.answer_id, field="answer_id")
        AnswerStatus(self.status)
        if self.question_index < 0:
            raise ValueError("question_index must be nonnegative")


@dataclass(frozen=True, kw_only=True)
class MultipleChoiceAnswer(SubmittedAnswer):
    chosen_index: int
    kind: Literal["multiple_choice"] = "multiple_choice"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.kind != "multiple_choice":
            raise ValueError("kind must be multiple_choice")
        if self.chosen_index < 0:
            raise ValueError("chosen_index must be nonnegative")


@dataclass(frozen=True, kw_only=True)
class OpenAnswer(SubmittedAnswer):
    text: str
    kind: Literal["open"] = "open"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.kind != "open":
            raise ValueError("kind must be open")


@dataclass(frozen=True, kw_only=True)
class OralAnswer(SubmittedAnswer):
    text: str
    kind: Literal["oral"] = "oral"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.kind != "oral":
            raise ValueError("kind must be oral")


type Answer = Annotated[
    MultipleChoiceAnswer | OpenAnswer | OralAnswer, Field(discriminator="kind")
]


@dataclass(frozen=True, kw_only=True)
class PracticeAttempt:
    id: str
    course_id: str
    generation_id: str
    format: GenerationFormat
    status: PracticeStatus
    created_at: datetime
    updated_at: datetime
    questions: tuple[GenerationQuestion, ...]
    answers: tuple[Answer, ...]

    def __post_init__(self) -> None:
        PracticeStatus(self.status)
        GenerationFormat(self.format)
        for field in ("id", "course_id", "generation_id"):
            require_uuid4(value=getattr(self, field), field=field)
        require_aware(value=self.created_at, field="created_at")
        require_aware(value=self.updated_at, field="updated_at")
        if self.format == GenerationFormat.SUMMARY:
            raise ValueError("summary cannot be practiced")
        is_mc = self.format == GenerationFormat.MULTIPLE_CHOICE
        if any(bool(question.options) != is_mc for question in self.questions):
            raise ValueError("question options must match the attempt format")
        self._validate_answers()

    def _validate_answers(self) -> None:
        ids = [answer.answer_id for answer in self.answers]
        indices = [answer.question_index for answer in self.answers]
        if len(set(ids)) != len(ids):
            raise ValueError("answer_id must be unique within the attempt")
        if len(set(indices)) != len(indices):
            raise ValueError("question_index must be unique within the attempt")
        for answer in self.answers:
            if not 0 <= answer.question_index < len(self.questions):
                raise ValueError("question_index is outside the attempt")
            if answer.kind != self.format:
                raise ValueError("answer format must match the question format")


PRACTICE_ADAPTER = TypeAdapter(PracticeAttempt)


def dump_practice_attempt(attempt: PracticeAttempt) -> str:
    return PRACTICE_ADAPTER.dump_json(attempt, indent=2).decode("utf-8") + "\n"


def load_practice_attempt(content: str) -> PracticeAttempt:
    return PRACTICE_ADAPTER.validate_json(content)

"""Self-contained practice snapshots and submitted answers."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter

from sbobina.generation_models import (
    DiscardCount,
    GenerationFormat,
    GenerationQuestion,
    GenerationSourceUsed,
)
from sbobina.grading_models import Judgement, JudgementOutcome
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
    submitted_at: datetime | None = None

    def __post_init__(self) -> None:
        require_uuid4(value=self.answer_id, field="answer_id")
        AnswerStatus(self.status)
        if self.submitted_at is not None:
            require_aware(value=self.submitted_at, field="submitted_at")
        if self.question_index < 0:
            raise ValueError("question_index must be nonnegative")


@dataclass(frozen=True, kw_only=True)
class MultipleChoiceAnswer(SubmittedAnswer):
    chosen_index: int
    status: AnswerStatus = AnswerStatus.GRADED
    kind: Literal["multiple_choice"] = "multiple_choice"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.kind != "multiple_choice":
            raise ValueError("kind must be multiple_choice")
        if self.chosen_index < 0:
            raise ValueError("chosen_index must be nonnegative")
        # Multiple choice is graded by code on submission, never later.
        if self.status != AnswerStatus.GRADED:
            raise ValueError("multiple choice answers must have graded status")


@dataclass(frozen=True, kw_only=True)
class TextAnswer(SubmittedAnswer):
    text: str
    judgement: Judgement | None = None
    self_grade: JudgementOutcome | None = None
    reason: str | None = None
    discarded: tuple[DiscardCount, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.text.strip():
            raise ValueError("text must not be blank")
        if self.self_grade is not None:
            JudgementOutcome(self.self_grade)
        check_grading_state(answer=self)


def check_grading_state(answer: TextAnswer) -> None:
    """Reject grading fields that disagree with the status.

    A graded answer without judgement could never be graded again, and a
    self-graded one without the student's grade would show no outcome. A
    judgement may stay on a self-graded answer: the student's grade wins.
    """
    status = answer.status
    if (status == AnswerStatus.SELF_GRADED) != (answer.self_grade is not None):
        raise ValueError("self_grade requires self_graded status and vice versa")
    if status == AnswerStatus.GRADED and answer.judgement is None:
        raise ValueError("graded status requires a judgement")
    if status == AnswerStatus.UNGRADED and answer.judgement is not None:
        raise ValueError("a judgement requires graded or self_graded status")
    if answer.reason is not None and status != AnswerStatus.UNGRADED:
        raise ValueError("reason is only allowed with ungraded status")


@dataclass(frozen=True, kw_only=True)
class OpenAnswer(TextAnswer):
    kind: Literal["open"] = "open"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.kind != "open":
            raise ValueError("kind must be open")


@dataclass(frozen=True, kw_only=True)
class OralAnswer(TextAnswer):
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
    sources: tuple[GenerationSourceUsed, ...] = ()

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

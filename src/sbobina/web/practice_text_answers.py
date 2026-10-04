from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

from sbobina.generation_models import GenerationFormat
from sbobina.grading_models import JudgementOutcome
from sbobina.practice_models import (
    AnswerStatus,
    OpenAnswer,
    OralAnswer,
    PracticeAttempt,
    PracticeStatus,
    require_uuid4,
)
from sbobina.web.errors import ConflictError, NotFoundError, ValidationError
from sbobina.web.path_locks import lock_for
from sbobina.web.practice_answers import AnswerTarget
from sbobina.web.practice_grading import PracticeServices, grade_answer, grading_mode
from sbobina.web.practice_store import load_attempt, practice_path, save_attempt


class TextSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    answer_id: str

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("La risposta non può essere vuota.")
        return value

    @field_validator("answer_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        require_uuid4(value=value, field="answer_id")
        return value


@dataclass(frozen=True, kw_only=True)
class AnswerLocation:
    courses_dir: Path
    course_id: str
    target: AnswerTarget


def attempt_file(location: AnswerLocation) -> Path:
    try:
        return practice_path(
            courses_dir=location.courses_dir,
            course_id=location.course_id,
            attempt_id=location.target.attempt_id,
        )
    except ValueError as error:
        raise NotFoundError(
            entity="Tentativo", id=location.target.attempt_id
        ) from error


@contextmanager
def grading_slot(location: AnswerLocation) -> Iterator[None]:
    # Held across the judge call, but per question: a duplicate POST waits for
    # the in-flight grade instead of calling Ollama twice, while the other
    # questions of the attempt are graded concurrently.
    question = location.target.question_index
    path = attempt_file(location=location).with_suffix(f".grade-{question}")
    with lock_for(path=path):
        yield


@contextmanager
def locked_attempt(location: AnswerLocation) -> Iterator[PracticeAttempt]:
    target = location.target
    path = attempt_file(location=location)
    # Lock order: grading slot, then submission, then the JSON write lock.
    # The submission lock is never held across the judge call.
    with lock_for(path=path.with_suffix(".submission")):
        attempt = load_attempt(
            courses_dir=location.courses_dir,
            course_id=location.course_id,
            attempt_id=target.attempt_id,
        )
        if (
            attempt.generation_id != target.gen_id
            or attempt.course_id != location.course_id
        ):
            raise NotFoundError(entity="Tentativo", id=target.attempt_id)
        if not 0 <= target.question_index < len(attempt.questions):
            raise NotFoundError(entity="Domanda", id=str(target.question_index))
        if attempt.format == GenerationFormat.MULTIPLE_CHOICE:
            raise ValidationError(message="La domanda non è aperta o orale.")
        yield attempt


def text_answer(
    attempt: PracticeAttempt, question_index: int
) -> OpenAnswer | OralAnswer:
    for answer in attempt.answers:
        if answer.question_index == question_index and isinstance(
            answer, (OpenAnswer, OralAnswer)
        ):
            return answer
    raise NotFoundError(entity="Risposta", id=str(question_index))


def apply_open(
    attempt: PracticeAttempt,
    question_index: int,
    body: TextSubmission,
) -> PracticeAttempt:
    for answer in attempt.answers:
        if (
            answer.answer_id == body.answer_id
            or answer.question_index == question_index
        ):
            if (
                isinstance(answer, (OpenAnswer, OralAnswer))
                and answer.answer_id == body.answer_id
                and answer.question_index == question_index
                and answer.text == body.text
            ):
                return attempt
            raise ConflictError(
                message="La risposta è già stata consegnata.",
                code="ANSWER_ALREADY_SUBMITTED",
            )
    answer_type = OpenAnswer if attempt.format == GenerationFormat.OPEN else OralAnswer
    answer = answer_type(
        answer_id=body.answer_id,
        question_index=question_index,
        text=body.text,
        submitted_at=datetime.now(tz=UTC),
    )
    return update_answer(attempt=attempt, answer=answer)


def update_answer(
    attempt: PracticeAttempt, answer: OpenAnswer | OralAnswer
) -> PracticeAttempt:
    answers = tuple(
        item for item in attempt.answers if item.question_index != answer.question_index
    )
    answers = tuple(sorted((*answers, answer), key=lambda item: item.question_index))
    status = PracticeStatus.IN_PROGRESS
    if len(answers) == len(attempt.questions):
        status = (
            PracticeStatus.SUBMITTED
            if any(item.status == AnswerStatus.UNGRADED for item in answers)
            else PracticeStatus.GRADED
        )
    return replace(
        attempt, answers=answers, status=status, updated_at=datetime.now(tz=UTC)
    )


def persist_answer(
    location: AnswerLocation,
    attempt: PracticeAttempt,
    answer: OpenAnswer | OralAnswer,
) -> PracticeAttempt:
    updated = update_answer(attempt=attempt, answer=answer)
    save_attempt(
        courses_dir=location.courses_dir, course_id=location.course_id, attempt=updated
    )
    return updated


def submit_text(
    location: AnswerLocation,
    body: TextSubmission,
    services: PracticeServices,
) -> PracticeAttempt:
    with grading_slot(location=location):
        with locked_attempt(location=location) as attempt:
            updated = apply_open(
                attempt=attempt,
                question_index=location.target.question_index,
                body=body,
            )
            if updated is not attempt:
                save_attempt(
                    courses_dir=location.courses_dir,
                    course_id=location.course_id,
                    attempt=updated,
                )
            answer = text_answer(
                attempt=updated, question_index=location.target.question_index
            )
        if (
            answer.status != AnswerStatus.UNGRADED
            or grading_mode(settings=services.settings) == "self"
        ):
            return updated
        return grade_and_store(
            location=location, attempt=updated, answer=answer, services=services
        )


def grade_and_store(
    location: AnswerLocation,
    attempt: PracticeAttempt,
    answer: OpenAnswer | OralAnswer,
    services: PracticeServices,
) -> PracticeAttempt:
    """Call the judge without the attempt lock, then store the result.

    The attempt is reloaded under the lock before writing: if the student
    self-graded or the answer changed meanwhile, their state wins and the
    judgement is not stored.
    """
    graded = grade_answer(attempt=attempt, answer=answer, services=services)
    with locked_attempt(location=location) as current:
        stored = text_answer(attempt=current, question_index=answer.question_index)
        if (
            stored.answer_id != answer.answer_id
            or stored.status != AnswerStatus.UNGRADED
        ):
            return current
        return persist_answer(location=location, attempt=current, answer=graded)


def retry_grade(
    location: AnswerLocation, services: PracticeServices
) -> PracticeAttempt:
    with grading_slot(location=location):
        with locked_attempt(location=location) as attempt:
            answer = text_answer(
                attempt=attempt, question_index=location.target.question_index
            )
        if answer.status != AnswerStatus.UNGRADED:
            return attempt
        return grade_and_store(
            location=location, attempt=attempt, answer=answer, services=services
        )


def submit_self_grade(
    location: AnswerLocation, outcome: JudgementOutcome
) -> PracticeAttempt:
    with locked_attempt(location=location) as attempt:
        answer = text_answer(
            attempt=attempt, question_index=location.target.question_index
        )
        updated = replace(
            answer, self_grade=outcome, status=AnswerStatus.SELF_GRADED, reason=None
        )
        return persist_answer(location=location, attempt=attempt, answer=updated)

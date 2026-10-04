from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sbobina.generation_models import EXPECTED_OPTION_COUNT, GenerationFormat
from sbobina.practice_models import (
    AnswerStatus,
    MultipleChoiceAnswer,
    PracticeAttempt,
    PracticeStatus,
)
from sbobina.web.errors import ConflictError, NotFoundError, ValidationError
from sbobina.web.path_locks import lock_for
from sbobina.web.practice_store import load_attempt, practice_path, save_attempt


@dataclass(frozen=True, kw_only=True)
class AnswerTarget:
    gen_id: str
    attempt_id: str
    question_index: int


def _validate_choice(
    attempt: PracticeAttempt, question_index: int, choice: int
) -> None:
    if not 0 <= question_index < len(attempt.questions):
        raise NotFoundError(entity="Domanda", id=str(question_index))
    if attempt.format != GenerationFormat.MULTIPLE_CHOICE:
        raise ValidationError(message="La domanda non è a crocette.")
    if type(choice) is not int or not 0 <= choice < EXPECTED_OPTION_COUNT:
        raise ValidationError(message="Scegli una delle quattro opzioni.")
    if any(answer.question_index == question_index for answer in attempt.answers):
        raise ConflictError(
            message="La risposta è già stata consegnata.",
            code="ANSWER_ALREADY_SUBMITTED",
        )


def apply_choice(
    attempt: PracticeAttempt, question_index: int, choice: int
) -> PracticeAttempt:
    _validate_choice(attempt=attempt, question_index=question_index, choice=choice)
    answer = MultipleChoiceAnswer(
        answer_id=str(uuid4()),
        question_index=question_index,
        status=AnswerStatus.GRADED,
        chosen_index=choice,
    )
    answers = (*attempt.answers, answer)
    status = (
        PracticeStatus.GRADED
        if len(answers) == len(attempt.questions)
        and all(answer.status == AnswerStatus.GRADED for answer in answers)
        else attempt.status
    )
    return replace(
        attempt, answers=answers, status=status, updated_at=datetime.now(tz=UTC)
    )


def submit_choice(
    courses_dir: Path, course_id: str, target: AnswerTarget, choice: int
) -> PracticeAttempt:
    try:
        path = practice_path(
            courses_dir=courses_dir, course_id=course_id, attempt_id=target.attempt_id
        )
    except ValueError as error:
        raise NotFoundError(entity="Tentativo", id=target.attempt_id) from error
    # A separate transaction lock avoids reacquiring save_attempt's non-reentrant lock.
    with lock_for(path=path.with_suffix(".submission")):
        attempt = load_attempt(
            courses_dir=courses_dir, course_id=course_id, attempt_id=target.attempt_id
        )
        if attempt.generation_id != target.gen_id or attempt.course_id != course_id:
            raise NotFoundError(entity="Tentativo", id=target.attempt_id)
        updated = apply_choice(
            attempt=attempt, question_index=target.question_index, choice=choice
        )
        save_attempt(courses_dir=courses_dir, course_id=course_id, attempt=updated)
    return updated

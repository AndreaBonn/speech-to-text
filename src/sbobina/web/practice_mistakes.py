from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sbobina.grading_models import JudgementOutcome
from sbobina.practice_models import Answer, PracticeAttempt
from sbobina.web.practice_payloads import answer_outcome

MISTAKE_OUTCOMES = frozenset({JudgementOutcome.INCORRECT, JudgementOutcome.PARTIAL})


@dataclass(frozen=True, kw_only=True)
class PracticeMistake:
    attempt: PracticeAttempt
    answer: Answer

    @property
    def submitted_at(self) -> datetime:
        return self.answer.submitted_at or self.attempt.created_at


def latest_mistakes(
    attempts: Iterable[PracticeAttempt], course_id: str
) -> list[PracticeMistake]:
    candidates = [
        PracticeMistake(attempt=attempt, answer=answer)
        for attempt in attempts
        if attempt.course_id == course_id
        for answer in attempt.answers
    ]
    latest: dict[tuple[str, int], PracticeMistake] = {}
    for item in sorted(candidates, key=lambda item: item.submitted_at, reverse=True):
        key = (item.attempt.generation_id, item.answer.question_index)
        latest.setdefault(key, item)
    return [
        item
        for item in latest.values()
        if answer_outcome(attempt=item.attempt, answer=item.answer) in MISTAKE_OUTCOMES
    ]

from typing import Any

from fastapi.encoders import jsonable_encoder

from sbobina.grading_models import (
    FULL_SCORE,
    PARTIAL_SCORE,
    ZERO_SCORE,
    JudgementOutcome,
)
from sbobina.practice_models import Answer, MultipleChoiceAnswer, PracticeAttempt

OUTCOME_SCORES = {
    JudgementOutcome.CORRECT: FULL_SCORE,
    JudgementOutcome.PARTIAL: PARTIAL_SCORE,
    JudgementOutcome.INCORRECT: ZERO_SCORE,
}


def answer_outcome(attempt: PracticeAttempt, answer: Answer) -> JudgementOutcome | None:
    if isinstance(answer, MultipleChoiceAnswer):
        correct = attempt.questions[answer.question_index].correct_index
        return (
            JudgementOutcome.CORRECT
            if answer.chosen_index == correct
            else JudgementOutcome.INCORRECT
        )
    if answer.self_grade is not None:
        return answer.self_grade
    return answer.judgement.outcome if answer.judgement else None


def answer_payload(attempt: PracticeAttempt, answer: Answer) -> dict[str, Any]:
    payload: dict[str, Any] = jsonable_encoder(obj=answer)
    outcome = answer_outcome(attempt=attempt, answer=answer)
    payload.update(
        outcome=outcome, score=OUTCOME_SCORES.get(outcome) if outcome else None
    )
    if not isinstance(answer, MultipleChoiceAnswer):
        # Always false since V6 passed (2026-10-05): the judge's verdict is a
        # grade. Kept so API v1 clients reading the field keep working.
        payload["is_suggestion"] = False
        if answer.judgement is not None:
            payload["judgement"].update(
                outcome=answer.judgement.outcome, score=answer.judgement.score
            )
    return payload

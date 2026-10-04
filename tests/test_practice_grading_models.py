from dataclasses import replace
from uuid import uuid4

import pytest

from sbobina.grading_models import JudgementOutcome
from sbobina.practice_models import AnswerStatus, OpenAnswer, OralAnswer


@pytest.mark.parametrize("answer_type", [OpenAnswer, OralAnswer])
@pytest.mark.parametrize("status", [AnswerStatus.UNGRADED, AnswerStatus.GRADED])
def test_self_grade_requires_final_status(
    answer_type: type[OpenAnswer] | type[OralAnswer],
    status: AnswerStatus,
) -> None:
    answer = answer_type(
        answer_id=str(uuid4()),
        question_index=0,
        text="Answer",
        self_grade=JudgementOutcome.CORRECT,
        status=AnswerStatus.SELF_GRADED,
    )
    assert answer.self_grade == JudgementOutcome.CORRECT
    with pytest.raises(ValueError, match="self_grade"):
        replace(answer, status=status)

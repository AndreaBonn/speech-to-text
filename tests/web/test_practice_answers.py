from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from test_practice_models import make_attempt

from sbobina.generation_models import GenerationFormat
from sbobina.grading_models import Judgement, JudgementOutcome
from sbobina.ollama_chat import ChatRequest
from sbobina.practice_models import AnswerStatus, OpenAnswer
from sbobina.settings import Settings
from sbobina.web.errors import ValidationError
from sbobina.web.gpu_lock import GpuArbiter
from sbobina.web.job_store import JobStore
from sbobina.web.practice_answers import apply_choice
from sbobina.web.practice_grading import PracticeServices, grade_answer


@pytest.mark.parametrize("choice", [-1, 4, True], ids=["negative", "past-end", "bool"])
def test_apply_choice_outside_the_four_options_is_rejected(choice: Any) -> None:
    attempt = make_attempt()
    assert apply_choice(attempt=attempt, question_index=0, choice=3).answers
    with pytest.raises(ValidationError, match="quattro opzioni"):
        apply_choice(attempt=attempt, question_index=0, choice=choice)


def test_grade_answer_already_graded_is_returned_without_calling_the_judge(
    tmp_path: Path,
) -> None:
    def judge(request: ChatRequest) -> str:
        raise AssertionError("an already graded answer must not reach the judge")

    services = PracticeServices(
        store=JobStore(data_dir=tmp_path),
        settings=Settings(),
        arbiter=GpuArbiter(),
        chat=judge,
    )
    graded = OpenAnswer(
        answer_id=str(uuid4()),
        question_index=0,
        text="Risposta",
        status=AnswerStatus.SELF_GRADED,
        self_grade=JudgementOutcome.CORRECT,
        judgement=Judgement(covered_points=(), missing_points=(), errors=()),
    )

    result = grade_answer(
        attempt=make_attempt(format=GenerationFormat.OPEN),
        answer=graded,
        services=services,
    )

    assert result is graded

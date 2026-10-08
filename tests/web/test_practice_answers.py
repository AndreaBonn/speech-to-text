from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from test_practice_models import make_attempt

from sbobina.correction import CorrectorUnavailableError
from sbobina.generation_models import GenerationFormat
from sbobina.grading_models import Judgement, JudgementOutcome
from sbobina.ollama_chat import ChatRequest
from sbobina.practice_models import AnswerStatus, MultipleChoiceAnswer, OpenAnswer
from sbobina.settings import Settings
from sbobina.web.errors import ValidationError
from sbobina.web.gpu_lock import GpuArbiter
from sbobina.web.job_store import JobStore
from sbobina.web.practice_answers import apply_choice
from sbobina.web.practice_grading import PracticeServices, grade_answer


@pytest.mark.parametrize("choice", [-1, 4, True], ids=["negative", "past-end", "bool"])
def test_apply_choice_outside_the_four_options_is_rejected(choice: Any) -> None:
    attempt = make_attempt()
    accepted = apply_choice(attempt=attempt, question_index=0, choice=3)
    assert isinstance(accepted.answers[0], MultipleChoiceAnswer)
    assert accepted.answers[0].chosen_index == 3
    with pytest.raises(ValidationError, match="quattro opzioni"):
        apply_choice(attempt=attempt, question_index=0, choice=choice)


@pytest.mark.parametrize(
    ("guard_whole_client", "expected_reason", "expected_calls"),
    [(True, "GPU_BUSY", 0), (False, "OLLAMA_UNAVAILABLE", 1)],
    ids=["local-engine-waits-for-gpu", "api-engine-skips-the-gpu-guard"],
)
def test_grade_answer_during_transcription_guards_only_the_local_judge(
    tmp_path: Path,
    guard_whole_client: bool,
    expected_reason: str,
    expected_calls: int,
) -> None:
    calls: list[ChatRequest] = []

    def judge(request: ChatRequest) -> str:
        calls.append(request)
        raise CorrectorUnavailableError("judge offline")

    arbiter = GpuArbiter()
    services = PracticeServices(
        store=JobStore(data_dir=tmp_path),
        settings=Settings(),
        arbiter=arbiter,
        chat=judge,
        guard_whole_client=guard_whole_client,
    )
    ungraded = OpenAnswer(answer_id=str(uuid4()), question_index=0, text="Risposta")

    with arbiter.transcription_lease(stage="transcribing"):
        result = grade_answer(
            attempt=make_attempt(format=GenerationFormat.OPEN),
            answer=ungraded,
            services=services,
        )

    assert (result.reason, len(calls)) == (expected_reason, expected_calls)


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

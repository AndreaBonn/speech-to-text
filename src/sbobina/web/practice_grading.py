import logging
from contextlib import nullcontext
from dataclasses import dataclass, replace
from typing import Literal

import httpx

from sbobina import llm_factory, platform_info
from sbobina.correction import CorrectorUnavailableError
from sbobina.grading import GradingChat, GradingRequest, GradingResult, grade
from sbobina.practice_models import (
    AnswerStatus,
    OpenAnswer,
    OralAnswer,
    PracticeAttempt,
)
from sbobina.settings import Settings
from sbobina.web.gpu_lock import GpuArbiter, GpuBusyError
from sbobina.web.job_store import JobStore

logger = logging.getLogger(__name__)
type GradingMode = Literal["judge", "self"]


def grading_mode(settings: Settings) -> GradingMode:
    if settings.practice_grading_mode != "auto":
        return settings.practice_grading_mode
    # A cloud judge does not need the local GPU (T024).
    if llm_factory.has_cloud_key(settings=settings):
        return "judge"
    runtime = platform_info.resolve_runtime(
        info=platform_info.detect_platform(),
        requested=platform_info.request_from_settings(config=settings),
    )
    return "judge" if runtime.device == "cuda" else "self"


@dataclass(frozen=True, kw_only=True)
class PracticeServices:
    store: JobStore
    settings: Settings
    arbiter: GpuArbiter
    chat: GradingChat
    # Same split as ChatServices (chat_turn.py): True guards the whole judge
    # call (local engine), False leaves the guard on the Ollama link alone,
    # already inside the chain the api engine built.
    guard_whole_client: bool = True


def grade_answer(
    attempt: PracticeAttempt,
    answer: OpenAnswer | OralAnswer,
    services: PracticeServices,
) -> OpenAnswer | OralAnswer:
    if answer.status != AnswerStatus.UNGRADED:
        return answer
    request = GradingRequest(
        question=attempt.questions[answer.question_index],
        format=attempt.format,
        answer=answer.text,
    )
    guard = (
        services.arbiter.chat_turn() if services.guard_whole_client else nullcontext()
    )
    try:
        with guard:
            result = grade(
                request=request,
                chat=services.chat,
                model=services.settings.ollama_model,
            )
    except GpuBusyError:
        logger.warning(
            "Practice judge skipped, GPU busy: question_index=%s",
            answer.question_index,
        )
        return replace(answer, reason="GPU_BUSY")
    except (ConnectionError, httpx.TransportError, CorrectorUnavailableError) as error:
        logger.warning("Practice judge unavailable: %s", error)
        return replace(answer, reason="OLLAMA_UNAVAILABLE")
    return graded_answer(answer=answer, result=result)


def graded_answer(
    answer: OpenAnswer | OralAnswer, result: GradingResult
) -> OpenAnswer | OralAnswer:
    return replace(
        answer,
        judgement=result.judgement,
        discarded=result.discarded,
        reason=result.error,
        status=AnswerStatus.GRADED if result.judgement else AnswerStatus.UNGRADED,
    )

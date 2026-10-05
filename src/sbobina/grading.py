import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources

from pydantic import ValidationError

from sbobina.correction import InvalidResponseError
from sbobina.generation_models import DiscardCount, GenerationFormat, GenerationQuestion
from sbobina.generation_validation import discard_counts
from sbobina.grading_models import Judgement, ProposedJudgement, validate_judgement
from sbobina.ollama_chat import ChatRequest, strip_markdown_fence
from sbobina.solution_points import extract_solution_points

PROMPT_FILE = "valutazione-v2.md"
logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 2
GRADING_FAILED = "GRADING_FAILED"
FORMAT_LABELS = {GenerationFormat.OPEN: "aperta", GenerationFormat.ORAL: "orale"}

type GradingChat = Callable[[ChatRequest], str]


@dataclass(frozen=True, kw_only=True)
class GradingRequest:
    question: GenerationQuestion
    format: GenerationFormat
    answer: str


@dataclass(frozen=True, kw_only=True)
class GradingResult:
    judgement: Judgement | None
    discarded: tuple[DiscardCount, ...] = ()

    @property
    def error(self) -> str | None:
        return GRADING_FAILED if self.judgement is None else None


def _build_request(request: GradingRequest, model: str) -> ChatRequest:
    points = extract_solution_points(
        solution=request.question.solution, format=request.format
    )
    numbered = "\n".join(
        f"[{index}] {point}" for index, point in enumerate(points, start=1)
    )
    return ChatRequest(
        model=model,
        system_prompt=resources.files("sbobina.prompts")
        .joinpath(PROMPT_FILE)
        .read_text(encoding="utf-8"),
        user_message=(
            f"Domanda: {request.question.question}\nFormato: {FORMAT_LABELS[request.format]}\n"
            f"{numbered}\n<risposta>\n{request.answer}\n</risposta>"
        ),
        schema=ProposedJudgement.model_json_schema(),
    )


def _credit_without_evidence(
    proposed: ProposedJudgement,
    judgement: Judgement,
    counts: Counter[str],
    attempt: int,
) -> bool:
    """F42: credit whose evidence is not in the answer (paraphrased or invented).

    Validation would drop it and grade the answer "errata"; no grade is better
    than a wrong one, so the reply counts as invalid.
    """
    if not proposed.covered_points or judgement.covered_points:
        return False
    logger.warning(
        "Judge credited %d points with no evidence found in the answer "
        "(attempt %d): %s",
        len(proposed.covered_points),
        attempt,
        dict(counts),
    )
    return True


def grade(*, request: GradingRequest, chat: GradingChat, model: str) -> GradingResult:
    chat_request = _build_request(request=request, model=model)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            content = strip_markdown_fence(content=chat(chat_request))
            proposed = ProposedJudgement.model_validate_json(content)
        except (InvalidResponseError, ValidationError) as error:
            logger.warning("Invalid judge reply (attempt %d): %s", attempt, error)
            continue
        judgement, counts = validate_judgement(
            proposed=proposed,
            solution=request.question.solution,
            answer=request.answer,
            format=request.format,
        )
        if _credit_without_evidence(
            proposed=proposed, judgement=judgement, counts=counts, attempt=attempt
        ):
            continue
        return GradingResult(
            judgement=judgement, discarded=discard_counts(counts=counts)
        )
    logger.error("Grading failed after %d attempts", MAX_ATTEMPTS)
    return GradingResult(judgement=None)

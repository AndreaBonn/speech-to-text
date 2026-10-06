import hashlib
import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from importlib import resources
from typing import Literal

from pydantic import ValidationError

from sbobina.correction import InvalidResponseError
from sbobina.json_salvage import complete_items, keep_valid
from sbobina.models import Transcript
from sbobina.ollama_chat import ChatRequest, strip_markdown_fence
from sbobina.study_blocks import StudyBlock, build_study_blocks
from sbobina.study_models import (
    DiscardCount,
    FailedBlock,
    RejectionReason,
    StudyChapter,
    StudyResponse,
    StudyResult,
)
from sbobina.study_validation import convert_chapter, validate_chapter

PROMPT_FILE = "studio-v2.md"
MAX_ATTEMPTS = 2
# Kept from an unreadable reply in the log: the result only marks the block failed.
LOGGED_REPLY_CHARS = 500
logger = logging.getLogger("sbobina")
REVISION_CHARS = 16
type StudyChat = Callable[[ChatRequest], str]
type StudyProgress = Callable[[int, int], None]


@dataclass(frozen=True, kw_only=True)
class StudyOptions:
    model: str
    block_words: int = 1200
    num_predict: int = 2048
    source_variant: Literal["original", "corrected"] = "original"
    source_revision: str = ""

    def __post_init__(self) -> None:
        if self.block_words <= 0 or self.num_predict <= 0:
            raise ValueError("Study limits must be positive")


@dataclass(frozen=True)
class _BlockResult:
    chapters: tuple[StudyChapter, ...]
    discarded: tuple[DiscardCount, ...]
    failed: tuple[FailedBlock, ...]


def source_revision(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:REVISION_CHARS]


def _build_request(options: StudyOptions) -> ChatRequest:
    prompt = (
        resources.files("sbobina.prompts")
        .joinpath(PROMPT_FILE)
        .read_text(encoding="utf-8")
    )
    return ChatRequest(
        model=options.model,
        system_prompt=prompt,
        user_message="",
        schema=StudyResponse.model_json_schema(),
        num_predict=options.num_predict,
    )


def _salvage(content: str) -> StudyResponse | None:
    """The chapters a reply cut by num_predict wrote in full.

    Measured on a real lecture: 3 of 5 blocks stop inside a chapter at 2048
    tokens, identically on retry, and a larger budget does not fit num_ctx
    with a 1200-word block. The complete chapters (1 or 2 per block) are kept.
    """
    chapters = keep_valid(
        items=complete_items(content=content, key="capitoli"),
        response_model=StudyResponse,
        field="chapters",
    )
    return StudyResponse.model_validate({"capitoli": chapters}) if chapters else None


def _request_response(chat: StudyChat, request: ChatRequest) -> StudyResponse | None:
    for _ in range(MAX_ATTEMPTS):
        content = ""
        try:
            content = strip_markdown_fence(content=chat(request))
            return StudyResponse.model_validate_json(content)
        except (InvalidResponseError, ValidationError):
            salvaged = _salvage(content=content)
            if salvaged is not None:
                return salvaged
            logger.warning(
                "Risposta dello studio non leggibile: %r", content[:LOGGED_REPLY_CHARS]
            )
    return None


def _validate_response(
    response: StudyResponse | None, block: StudyBlock, transcript: Transcript
) -> _BlockResult:
    if response is None:
        return _BlockResult(
            chapters=(),
            discarded=(),
            failed=(FailedBlock(start=block.start, end=block.end),),
        )
    chapters = []
    counts: Counter[RejectionReason] = Counter()
    for proposed in response.chapters:
        chapter, discarded = validate_chapter(
            chapter=convert_chapter(proposed=proposed),
            segments=block.segments,
            allowed=block.allowed,
            original=transcript.segments,
        )
        counts.update(discarded)
        if chapter is not None:
            chapters.append(chapter)
    return _BlockResult(
        chapters=tuple(chapters),
        discarded=tuple(
            DiscardCount(reason=r, count=n) for r, n in sorted(counts.items())
        ),
        failed=(),
    )


def _assemble_result(
    outcomes: list[_BlockResult], transcript: Transcript, options: StudyOptions
) -> StudyResult:
    counts: Counter[RejectionReason] = Counter()
    for outcome in outcomes:
        counts.update({count.reason: count.count for count in outcome.discarded})
    chapters = [chapter for outcome in outcomes for chapter in outcome.chapters]
    return StudyResult(
        source_variant=options.source_variant,
        source_revision=options.source_revision,
        model=options.model,
        prompt_version=PROMPT_FILE.removesuffix(".md"),
        generated_at=datetime.now(tz=UTC).isoformat(),
        chapters=tuple(sorted(chapters, key=lambda c: c.start)),
        discarded=tuple(
            DiscardCount(reason=r, count=n) for r, n in sorted(counts.items())
        ),
        failed_blocks=tuple(
            failed for outcome in outcomes for failed in outcome.failed
        ),
    )


def generate_study(
    transcript: Transcript,
    chat: StudyChat,
    options: StudyOptions,
    on_progress: StudyProgress | None = None,
) -> StudyResult:
    """Generate grounded chapters; unavailable chat errors abort without file I/O."""
    template = _build_request(options=options)
    blocks = build_study_blocks(transcript=transcript, max_words=options.block_words)
    outcomes = []
    for done, block in enumerate(blocks, start=1):
        response = _request_response(
            chat=chat, request=replace(template, user_message=block.text)
        )
        outcomes.append(
            _validate_response(response=response, block=block, transcript=transcript)
        )
        if on_progress is not None:
            on_progress(done, len(blocks))
    return _assemble_result(outcomes=outcomes, transcript=transcript, options=options)

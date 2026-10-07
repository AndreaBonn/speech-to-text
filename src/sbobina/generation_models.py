"""Domain and LLM-response models for course generations (D5, plan C3).

Mirrors study_models.py: frozen dataclasses hold the persisted domain record,
pydantic models with Italian aliases parse the raw LLM JSON response. The two
never mix: a ``Proposed*`` class is never written to disk, a domain dataclass
is never fed directly to ``chat_json``.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

MIN_QUESTION_COUNT = 1
# num_ctx is fixed at 8192: past 10 items the reply budget leaves under
# ~1000 words of material (T036 measurements).
MAX_QUESTION_COUNT = 10
MAX_TOPIC_LENGTH = 200
EXPECTED_OPTION_COUNT = 4
_PASSAGE_PATTERN = r"^P[0-9]+$"


# An oral outline lists its points separated by this (solution_points.py).
ORAL_POINT_SEPARATOR = " | "


class GenerationFormat(StrEnum):
    MULTIPLE_CHOICE = "multiple_choice"
    OPEN = "open"
    ORAL = "oral"
    SUMMARY = "summary"


class GenerationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class GenerationSources(BaseModel):
    """Explicit source selection; both empty means the whole course."""

    model_config = ConfigDict(frozen=True)
    doc_ids: tuple[str, ...] = ()
    job_ids: tuple[str, ...] = ()


class GenerationRequest(BaseModel):
    """API body for POST .../generations; field errors map to 422 (T034)."""

    model_config = ConfigDict(frozen=True)
    format: GenerationFormat
    count: int = Field(ge=MIN_QUESTION_COUNT, le=MAX_QUESTION_COUNT)
    topic: str = Field(default="", max_length=MAX_TOPIC_LENGTH)
    sources: GenerationSources = Field(default_factory=GenerationSources)


@dataclass(frozen=True, kw_only=True)
class GenerationCitation:
    """Citation as persisted, resolved against the source (T030/T033).

    ``passage_id`` is the retrieval's own stable id (e.g. ``"manuale:p214:c0"``
    or ``"Ljob-1-S3"``), unlike the per-call "P3" label the prompt used, which
    means nothing once the generation outlives that one call. Exactly one of
    (doc_id, page) or (job_id, timestamp) is set, mirroring
    GenerationSourceUsed below.
    """

    passage_id: str
    quote: str
    doc_id: str | None
    page: int | None
    job_id: str | None
    timestamp: float | None

    def __post_init__(self) -> None:
        is_doc = self.doc_id is not None
        is_lecture = self.job_id is not None
        if is_doc == is_lecture:
            raise ValueError("exactly one of doc_id or job_id must be set")
        if is_doc != (self.page is not None):
            raise ValueError("page is set only for document citations")
        if is_lecture != (self.timestamp is not None):
            raise ValueError("timestamp is set only for lecture citations")


@dataclass(frozen=True)
class GenerationQuestion:
    """One question as persisted; options/correct_index are set only for
    multiple_choice. For "aperte" and "orale" the solution is free text
    (orale packs its outline points into one string, joined by " | ")."""

    question: str
    options: tuple[str, ...]
    correct_index: int | None
    solution: str
    citations: tuple[GenerationCitation, ...]

    def __post_init__(self) -> None:
        if self.options:
            if len(self.options) != EXPECTED_OPTION_COUNT:
                raise ValueError(
                    f"expected {EXPECTED_OPTION_COUNT} options, got {len(self.options)}"
                )
            if len(set(self.options)) != len(self.options) or not all(
                option.strip() for option in self.options
            ):
                raise ValueError("options must be distinct and not blank")
            if self.correct_index is None or not 0 <= self.correct_index < len(
                self.options
            ):
                raise ValueError(
                    f"correct_index must be 0-{len(self.options) - 1}, "
                    f"got {self.correct_index}"
                )
        elif self.correct_index is not None:
            raise ValueError("correct_index is set without options")


@dataclass(frozen=True)
class SummarySentence:
    text: str
    citations: tuple[GenerationCitation, ...]


@dataclass(frozen=True)
class SummarySection:
    title: str
    sentences: tuple[SummarySentence, ...]


@dataclass(frozen=True)
class DiscardCount:
    reason: str
    count: int

    def __post_init__(self) -> None:
        if self.count < 0:
            raise ValueError(f"discard count must not be negative, got {self.count}")


@dataclass(frozen=True)
class GenerationSourceUsed:
    """One source consulted, as persisted in `sources` per ADR D5."""

    doc_id: str | None
    sha256: str | None
    job_id: str | None
    revision: str | None

    def __post_init__(self) -> None:
        is_doc = self.doc_id is not None
        is_lecture = self.job_id is not None
        if is_doc == is_lecture:
            raise ValueError("exactly one of doc_id or job_id must be set")
        if is_doc != (self.sha256 is not None):
            raise ValueError("sha256 is set only for document sources")
        if is_lecture != (self.revision is not None):
            raise ValueError("revision is set only for lecture sources")


@dataclass(frozen=True, kw_only=True)
class GenerationRecord:
    """Persisted record for `generations/<id>.json`."""

    id: str
    format: GenerationFormat
    status: GenerationStatus
    requested_count: int
    topic: str
    model: str
    prompt_version: str
    generated_at: str
    sources: tuple[GenerationSourceUsed, ...]
    discarded: tuple[DiscardCount, ...]
    questions: tuple[GenerationQuestion, ...]
    sections: tuple[SummarySection, ...]
    error: str | None
    # Appended last, defaulted: a record saved before T034 has no such key
    # in its JSON and must still load (see test_generation_models.py).
    requested_sources: GenerationSources = field(default_factory=GenerationSources)
    # Which provider/model served how many requests (T024); absent before it.
    served_by: dict[str, int] | None = None
    retrieval_mode: dict[str, object] | None = None

    def __post_init__(self) -> None:
        self._validate_status()
        self._validate_format_content()

    def _validate_status(self) -> None:
        is_done = self.status is GenerationStatus.DONE
        has_content = bool(self.questions) or bool(self.sections)
        if has_content and not is_done:
            raise ValueError(f"content is set only when done, got {self.status}")
        if (self.error is not None) != (self.status is GenerationStatus.FAILED):
            raise ValueError(f"error is set only when failed, got {self.status}")

    def _validate_format_content(self) -> None:
        is_summary = self.format is GenerationFormat.SUMMARY
        if self.sections and not is_summary:
            raise ValueError(
                f"sections are set only for the summary format, got {self.format}"
            )
        if self.questions and is_summary:
            raise ValueError("questions are set for a summary generation")
        is_mc = self.format is GenerationFormat.MULTIPLE_CHOICE
        if any(question.options for question in self.questions) and not is_mc:
            raise ValueError(f"options are set for a {self.format} question")
        if is_mc and any(not question.options for question in self.questions):
            raise ValueError("a multiple_choice question needs its options")


class ProposedCitation(BaseModel):
    passage: str = Field(alias="passaggio", pattern=_PASSAGE_PATTERN)
    quote: str = Field(alias="testo")


class ProposedMultipleChoiceQuestion(BaseModel):
    question: str = Field(alias="domanda")
    options: list[str] = Field(alias="opzioni")
    correct_index: int = Field(alias="corretta", ge=0, le=EXPECTED_OPTION_COUNT - 1)
    solution: str = Field(alias="soluzione")
    citations: list[ProposedCitation] = Field(alias="citazioni")

    @field_validator("options")
    @classmethod
    def _validate_option_count(cls, value: list[str]) -> list[str]:
        if len(value) != EXPECTED_OPTION_COUNT:
            raise ValueError(
                f"expected {EXPECTED_OPTION_COUNT} options, got {len(value)}"
            )
        return value


class MultipleChoiceResponse(BaseModel):
    questions: list[ProposedMultipleChoiceQuestion] = Field(alias="domande")


class ProposedSummarySentence(BaseModel):
    text: str = Field(alias="testo")
    citations: list[ProposedCitation] = Field(alias="citazioni")


class ProposedSummarySection(BaseModel):
    title: str = Field(alias="titolo")
    sentences: list[ProposedSummarySentence] = Field(alias="frasi")


class SummaryResponse(BaseModel):
    sections: list[ProposedSummarySection] = Field(alias="sezioni")


GENERATION_ADAPTER = TypeAdapter(GenerationRecord)


def dump_generation(record: GenerationRecord) -> str:
    return GENERATION_ADAPTER.dump_json(record, indent=2).decode("utf-8") + "\n"


def load_generation(content: str) -> GenerationRecord:
    return GENERATION_ADAPTER.validate_json(content)

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class RejectionReason(StrEnum):
    PASSAGE_NOT_IN_BLOCK = "PASSAGE_NOT_IN_BLOCK"
    QUOTE_NOT_FOUND = "QUOTE_NOT_FOUND"
    QUOTE_TOO_SHORT = "QUOTE_TOO_SHORT"
    QUOTE_TOO_LONG = "QUOTE_TOO_LONG"
    TERM_NOT_IN_QUOTE = "TERM_NOT_IN_QUOTE"
    # The quote repeats inside its passage and the saved form cannot tell which.
    AMBIGUOUS_QUOTE = "AMBIGUOUS_QUOTE"


@dataclass(frozen=True)
class Rejection:
    reason: RejectionReason


@dataclass(frozen=True)
class Citation:
    segment_index: int
    quote: str


@dataclass(frozen=True)
class WordReference:
    segment_index: int
    word_index: int


@dataclass(frozen=True)
class CitationMatch:
    segment_index: int
    word_indices: tuple[WordReference, ...]
    timestamp: float


@dataclass(frozen=True)
class SummaryItem:
    text: str
    citations: tuple[Citation, ...]


@dataclass(frozen=True)
class ConceptItem:
    term: str
    explanation: str
    citations: tuple[Citation, ...]


@dataclass(frozen=True)
class QuestionItem:
    question: str
    citations: tuple[Citation, ...]


type StudyItem = SummaryItem | ConceptItem | QuestionItem


@dataclass(frozen=True)
class ValidatedItem:
    item: StudyItem
    citations: tuple[CitationMatch, ...]


@dataclass(frozen=True, kw_only=True)
class StudyChapter:
    title: str
    start: float
    summary: tuple[SummaryItem, ...]
    concepts: tuple[ConceptItem, ...]
    questions: tuple[QuestionItem, ...]


@dataclass(frozen=True)
class DiscardCount:
    reason: RejectionReason
    count: int


@dataclass(frozen=True)
class FailedBlock:
    start: float
    end: float


@dataclass(frozen=True, kw_only=True)
class StudyResult:
    source_variant: Literal["original", "corrected"]
    source_revision: str
    model: str
    prompt_version: str
    generated_at: str
    chapters: tuple[StudyChapter, ...]
    discarded: tuple[DiscardCount, ...]
    failed_blocks: tuple[FailedBlock, ...]


class ProposedCitation(BaseModel):
    passage: str = Field(alias="passaggio", pattern=r"^S[0-9]+$")
    quote: str = Field(alias="testo")

    @property
    def segment_index(self) -> int:
        return int(self.passage[1:])


class ProposedSummary(BaseModel):
    text: str = Field(alias="testo")
    citations: list[ProposedCitation] = Field(alias="citazioni")


class ProposedConcept(BaseModel):
    term: str = Field(alias="termine")
    explanation: str = Field(alias="spiegazione")
    citations: list[ProposedCitation] = Field(alias="citazioni")


class ProposedQuestion(BaseModel):
    question: str = Field(alias="domanda")
    citations: list[ProposedCitation] = Field(alias="citazioni")


class ProposedChapter(BaseModel):
    title: str = Field(alias="titolo")
    start: float = Field(alias="inizio")
    summary: list[ProposedSummary] = Field(alias="riassunto")
    concepts: list[ProposedConcept] = Field(alias="concetti")
    questions: list[ProposedQuestion] = Field(alias="domande")


class StudyResponse(BaseModel):
    chapters: list[ProposedChapter] = Field(alias="capitoli")

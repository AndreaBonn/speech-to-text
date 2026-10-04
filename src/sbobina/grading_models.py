from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from sbobina.generation_models import GenerationFormat
from sbobina.solution_points import extract_solution_points
from sbobina.study_citations import (
    MAX_QUOTE_WORDS,
    MIN_QUOTE_WORDS,
    normalize_tokens,
)

FULL_SCORE = 1.0
PARTIAL_SCORE = 0.5
ZERO_SCORE = 0.0


class JudgementOutcome(StrEnum):
    CORRECT = "corretta"
    PARTIAL = "parziale"
    INCORRECT = "errata"


class DiscardReason(StrEnum):
    POINT_NOT_IN_SOLUTION = "POINT_NOT_IN_SOLUTION"
    EVIDENCE_NOT_IN_ANSWER = "EVIDENCE_NOT_IN_ANSWER"
    MISSING_POINT_NOT_IN_SOLUTION = "MISSING_POINT_NOT_IN_SOLUTION"
    ERROR_NOT_IN_ANSWER = "ERROR_NOT_IN_ANSWER"
    QUOTE_LENGTH_OUT_OF_RANGE = "QUOTE_LENGTH_OUT_OF_RANGE"


class ProposedCoveredPoint(BaseModel):
    point: str = Field(alias="punto")
    evidence: str = Field(alias="prova")


class ProposedError(BaseModel):
    phrase: str = Field(alias="frase")
    reason: str = Field(alias="motivo")


class ProposedJudgement(BaseModel):
    model_config = ConfigDict(extra="ignore")
    covered_points: list[ProposedCoveredPoint] = Field(alias="punti_coperti")
    missing_points: list[str] = Field(alias="punti_mancanti")
    errors: list[ProposedError] = Field(alias="errori")


@dataclass(frozen=True, kw_only=True)
class CoveredPoint:
    point: str
    evidence: str


@dataclass(frozen=True, kw_only=True)
class GradingError:
    phrase: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class Judgement:
    covered_points: tuple[CoveredPoint, ...]
    missing_points: tuple[str, ...]
    errors: tuple[GradingError, ...]

    @property
    def outcome(self) -> JudgementOutcome:
        if not self.covered_points:
            return JudgementOutcome.INCORRECT
        if not self.missing_points and not self.errors:
            return JudgementOutcome.CORRECT
        return JudgementOutcome.PARTIAL

    @property
    def score(self) -> float:
        return {
            JudgementOutcome.CORRECT: FULL_SCORE,
            JudgementOutcome.PARTIAL: PARTIAL_SCORE,
            JudgementOutcome.INCORRECT: ZERO_SCORE,
        }[self.outcome]


def contains_quote(text: str, quote: str) -> bool:
    tokens = normalize_tokens(text=text)
    needle = normalize_tokens(text=quote)
    return bool(needle) and any(
        tokens[index : index + len(needle)] == needle
        for index in range(len(tokens) - len(needle) + 1)
    )


def has_quote_length(quote: str) -> bool:
    # Same bounds as source citations: a one- or two-word quote matches almost
    # any answer by chance and would credit a point the student never made.
    return MIN_QUOTE_WORDS <= len(normalize_tokens(text=quote)) <= MAX_QUOTE_WORDS


def _validate_covered(
    proposed: ProposedJudgement, solution: str, answer: str
) -> tuple[tuple[CoveredPoint, ...], Counter[str]]:
    covered = []
    counts: Counter[str] = Counter()
    for item in proposed.covered_points:
        if not contains_quote(text=solution, quote=item.point):
            counts[DiscardReason.POINT_NOT_IN_SOLUTION] += 1
        elif not contains_quote(text=answer, quote=item.evidence):
            counts[DiscardReason.EVIDENCE_NOT_IN_ANSWER] += 1
        elif not has_quote_length(quote=item.evidence):
            counts[DiscardReason.QUOTE_LENGTH_OUT_OF_RANGE] += 1
        else:
            covered.append(CoveredPoint(point=item.point, evidence=item.evidence))
    return tuple(covered), counts


def _point_index(points: tuple[str, ...], quote: str) -> int | None:
    normalized = normalize_tokens(text=quote)
    exact = next(
        (
            index
            for index, point in enumerate(points)
            if normalize_tokens(text=point) == normalized
        ),
        None,
    )
    if exact is not None:
        return exact
    return next(
        (
            index
            for index, point in enumerate(points)
            if contains_quote(text=point, quote=quote)
        ),
        None,
    )


def _partition_points(
    points: tuple[str, ...], covered: tuple[CoveredPoint, ...], missing: tuple[str, ...]
) -> tuple[tuple[CoveredPoint, ...], tuple[str, ...]]:
    accepted = {normalize_tokens(text=item.point): item for item in covered}
    absent = {normalize_tokens(text=point): point for point in missing}
    represented = {
        _point_index(points=points, quote=quote)
        for quote in (*[item.point for item in accepted.values()], *missing)
    }
    # Preserve anchored entries; one quote never credits multiple solution units.
    for index, point in enumerate(points):
        if index not in represented:
            absent.setdefault(normalize_tokens(text=point), point)
    return tuple(accepted.values()), tuple(absent.values())


def _validate_errors(
    proposed: ProposedJudgement, answer: str
) -> tuple[tuple[GradingError, ...], Counter[str]]:
    errors = []
    counts: Counter[str] = Counter()
    for error in proposed.errors:
        if not contains_quote(text=answer, quote=error.phrase):
            counts[DiscardReason.ERROR_NOT_IN_ANSWER] += 1
        elif not has_quote_length(quote=error.phrase):
            counts[DiscardReason.QUOTE_LENGTH_OUT_OF_RANGE] += 1
        else:
            errors.append(GradingError(phrase=error.phrase, reason=error.reason))
    return tuple(errors), counts


def validate_judgement(
    proposed: ProposedJudgement, solution: str, answer: str, format: GenerationFormat
) -> tuple[Judgement, Counter[str]]:
    covered, counts = _validate_covered(
        proposed=proposed, solution=solution, answer=answer
    )
    missing = []
    for point in proposed.missing_points:
        if contains_quote(text=solution, quote=point):
            missing.append(point)
        else:
            counts[DiscardReason.MISSING_POINT_NOT_IN_SOLUTION] += 1
    errors, error_counts = _validate_errors(proposed=proposed, answer=answer)
    counts.update(error_counts)
    accepted, absent = _partition_points(
        points=extract_solution_points(solution=solution, format=format),
        covered=covered,
        missing=tuple(missing),
    )
    return Judgement(
        covered_points=accepted, missing_points=absent, errors=errors
    ), counts

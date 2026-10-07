"""Pure retrieval quality metrics against a gold set.

Gold references are stable across reindex: a document re-extracted or a
lecture re-transcribed keeps the same filename/page or job_id/time interval,
even though production's own passage ids (doc_id, chunk index) can change.
That is why DocumentRef and LectureRef use filename and a time interval
instead of production's RetrievalSource. Pure, no I/O.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

PairedOutcome = Literal["win", "loss", "tie"]
# Blind judging scale: 2 answers, 1 partial, 0 no. Only a full answer is a hit.
RELEVANT_VOTE = 2


@dataclass(frozen=True)
class DocumentRef:
    filename: str
    page: int

    def __post_init__(self) -> None:
        # A page-0 typo in the gold would never match and silently lower recall.
        if self.page < 1:
            raise ValueError(f"page must be >= 1, got {self.page} for {self.filename}")


@dataclass(frozen=True)
class LectureRef:
    job_id: str
    start_s: float
    end_s: float

    def __post_init__(self) -> None:
        if not 0 <= self.start_s <= self.end_s:
            raise ValueError(
                f"invalid interval [{self.start_s}, {self.end_s}] for {self.job_id}"
            )


PassageRef = DocumentRef | LectureRef


def _intervals_overlap(
    *, start_a: float, end_a: float, start_b: float, end_b: float
) -> bool:
    """Check whether two closed intervals overlap or touch at a boundary.

    Parameters
    ----------
    start_a, end_a : float
        First interval, in seconds.
    start_b, end_b : float
        Second interval, in seconds.

    Returns
    -------
    bool
        True if the intervals share at least one point, including a shared
        boundary (`end_a == start_b`). False only when a real gap separates
        them.
    """
    return start_a <= end_b and start_b <= end_a


def _refs_match(*, passage_ref: PassageRef, gold_ref: PassageRef) -> bool:
    if isinstance(passage_ref, DocumentRef) and isinstance(gold_ref, DocumentRef):
        return (passage_ref.filename, passage_ref.page) == (
            gold_ref.filename,
            gold_ref.page,
        )
    if isinstance(passage_ref, LectureRef) and isinstance(gold_ref, LectureRef):
        return passage_ref.job_id == gold_ref.job_id and _intervals_overlap(
            start_a=passage_ref.start_s,
            end_a=passage_ref.end_s,
            start_b=gold_ref.start_s,
            end_b=gold_ref.end_s,
        )
    return False


def is_relevant(*, passage_ref: PassageRef, gold_refs: Sequence[PassageRef]) -> bool:
    """Check whether a retrieved passage matches any gold reference.

    A DocumentRef matches on identical filename and page. A LectureRef
    matches on identical job_id and an overlapping (or boundary-touching)
    time interval. A DocumentRef and a LectureRef never match each other.
    """
    return any(
        _refs_match(passage_ref=passage_ref, gold_ref=gold_ref)
        for gold_ref in gold_refs
    )


def first_relevant_rank(
    *, ranked_refs: Sequence[PassageRef], gold_refs: Sequence[PassageRef]
) -> int | None:
    """Return the 1-based rank of the first relevant passage, or None.

    Parameters
    ----------
    ranked_refs : Sequence[PassageRef]
        Retrieved references, ordered best-first.
    gold_refs : Sequence[PassageRef]
        The gold references for the question being evaluated.

    Returns
    -------
    int | None
        The 1-based rank of the first entry in `ranked_refs` that is
        relevant (per `is_relevant`), or None if none is relevant.
    """
    for rank, ref in enumerate(ranked_refs, start=1):
        if is_relevant(passage_ref=ref, gold_refs=gold_refs):
            return rank
    return None


@dataclass(frozen=True)
class RankedPassage:
    passage_id: str
    ref: PassageRef


def first_judged_rank(
    *,
    ranked: Sequence[RankedPassage],
    gold_refs: Sequence[PassageRef],
    votes: Mapping[str, int],
) -> int | None:
    """1-based rank of the first passage judged a full answer or matching the gold.

    Blind pooled judgments (votes by passage id) extend the hand-annotated
    gold: a relevant passage nobody annotated must not count as a miss.
    """
    for rank, passage in enumerate(ranked, start=1):
        if votes.get(passage.passage_id, 0) >= RELEVANT_VOTE:
            return rank
        if is_relevant(passage_ref=passage.ref, gold_refs=gold_refs):
            return rank
    return None


def merge_verdicts(
    *, verdict_files: Sequence[Mapping[str, Mapping[str, int]]]
) -> dict[str, dict[str, int]]:
    """Union of judging files, merged per question.

    Successive judging rounds hold different passages of the same question,
    so a later file adds votes instead of replacing the question's entry.
    """
    merged: dict[str, dict[str, int]] = {}
    for verdicts in verdict_files:
        for question_id, question_votes in verdicts.items():
            merged.setdefault(question_id, {}).update(question_votes)
    return merged


def recall_at_k(*, rank: int | None, k: int) -> float:
    """Hit@k for a single question: 1.0 if a relevant rank is within k."""
    return 1.0 if rank is not None and rank <= k else 0.0


def mean_recall_at_k(*, ranks: Sequence[int | None], k: int) -> float:
    """Average hit@k across multiple questions, 0.0 if `ranks` is empty."""
    if not ranks:
        return 0.0
    return sum(recall_at_k(rank=rank, k=k) for rank in ranks) / len(ranks)


def mrr_at_k(*, rank: int | None, k: int) -> float:
    """Reciprocal rank for a single question, 0.0 if beyond k or missing."""
    if rank is None or rank > k:
        return 0.0
    return 1.0 / rank


def paired_outcome(
    *, baseline_rank: int | None, system_rank: int | None, k: int
) -> PairedOutcome:
    """Compare a system against a baseline on hit@k for one question.

    Parameters
    ----------
    baseline_rank : int | None
        First relevant rank for the baseline system.
    system_rank : int | None
        First relevant rank for the system under test.
    k : int
        Cutoff shared by both hit@k computations.

    Returns
    -------
    PairedOutcome
        "win" if the system hits and the baseline misses, "loss" for the
        opposite, "tie" otherwise (both hit or both miss).
    """
    baseline_hit = recall_at_k(rank=baseline_rank, k=k) == 1.0
    system_hit = recall_at_k(rank=system_rank, k=k) == 1.0
    if system_hit and not baseline_hit:
        return "win"
    if baseline_hit and not system_hit:
        return "loss"
    return "tie"


def count_above(*, scores: Sequence[float], threshold: float) -> int:
    """Count similarity scores at or above `threshold`."""
    return sum(1 for score in scores if score >= threshold)

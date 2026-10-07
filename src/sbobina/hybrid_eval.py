"""Pure logic for the hybrid retrieval eval harness (T013, specs/004-hybrid-retrieval).

scripts/eval_hybrid.py is the I/O edge: it opens the corpus, queries Ollama
for embeddings and reads/writes the on-disk vector cache. This module has no
I/O, so every rule is testable without a database or a network call.

Lecture and document units both carry a stable PassageRef (DocumentRef or
LectureRef) for gold scoring, not production's RetrievalSource (which has no
filename and no lecture end time). Documents reuse the FTS passage as the
unit: the same granularity production's bm25 already ranks. Lectures
redefine the unit as a ~250-word partition_lecture_segments window (plan.md
Dis.3 option B, scoped to this harness only): a BM25 hit lands on a raw
Whisper segment, so aggregate_lecture_hits_to_windows projects it onto the
window containing it before the lists are fused by passage_id. This lets
fuse_by_rank (production) merge BM25 and dense lists unchanged.
"""

import hashlib
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from sbobina.embedding_prompts import format_document
from sbobina.lecture_windows import partition_lecture_segments
from sbobina.rank_fusion import fuse_by_rank
from sbobina.retrieval_metrics import DocumentRef, LectureRef, PassageRef
from sbobina.search_text import Passage

PROMPT_PROBE = "{text}"
PROMPT_TAG_LENGTH = 8


@dataclass(frozen=True)
class DocUnit:
    passage_id: str
    text: str
    ref: DocumentRef


@dataclass(frozen=True)
class LectureUnit:
    passage_id: str
    text: str
    ref: LectureRef


EvalUnit = DocUnit | LectureUnit
RankedUnits = Sequence[tuple[float, EvalUnit]]


def content_hash(text: str) -> str:
    """Stable cache key for one unit's text, independent of its passage_id."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def segment_positions(segments: Sequence[Passage]) -> dict[int, int]:
    """Map each Passage.segment_index to its position in `segments`.

    passages_from_transcript drops empty-text segments, so segment_index (the
    original transcript position) and the list position diverge once a gap
    happened upstream: this is the join key a raw BM25 hit needs to find the
    window that contains it.
    """
    return {
        passage.segment_index: position for position, passage in enumerate(segments)
    }


def build_lecture_units(
    *,
    job_id: str,
    segments: Sequence[Passage],
    segment_ends: Sequence[float],
    window_words: int,
) -> tuple[list[tuple[int, int]], list[LectureUnit]]:
    """Whole-transcript ~window_words windows: the lecture candidate universe.

    Reuses production's partition_lecture_segments. Passage has no end field,
    so segment_ends[i] must come from the same filtered pass as `segments`.
    """
    spans = partition_lecture_segments(
        segments=list(segments), window_words=window_words
    )
    units = [
        LectureUnit(
            passage_id=f"L{job_id}-W{position}",
            text=" ".join(segment.text for segment in segments[first : last + 1]),
            ref=LectureRef(
                job_id=job_id,
                start_s=segments[first].start,
                end_s=segment_ends[last],
            ),
        )
        for position, (first, last) in enumerate(spans)
    ]
    return spans, units


def _window_containing(
    *, spans: Sequence[tuple[int, int]], position: int
) -> int | None:
    for index, (first, last) in enumerate(spans):
        if first <= position <= last:
            return index
    return None


def aggregate_lecture_hits_to_windows(
    *,
    hits: Sequence[tuple[float, int]],
    segment_positions: Mapping[int, int],
    spans: Sequence[tuple[int, int]],
    units: Sequence[LectureUnit],
) -> list[tuple[float, LectureUnit]]:
    """Project raw-segment BM25 hits onto the window units they fall inside.

    A window hit by more than one matched segment keeps the best (lowest,
    ascending-better like bm25()) score. A hit whose segment_index has no
    known position, or whose position falls in no span, is dropped: both are
    data the eval harness could not resolve, not a candidate.
    """
    best: dict[int, float] = {}
    for score, segment_index in hits:
        position = segment_positions.get(segment_index)
        if position is None:
            continue
        window_index = _window_containing(spans=spans, position=position)
        if window_index is None:
            continue
        if window_index not in best or score < best[window_index]:
            best[window_index] = score
    return [(score, units[window_index]) for window_index, score in best.items()]


def dense_scores(
    *, query_vector: Sequence[float], unit_vectors: np.ndarray
) -> np.ndarray:
    """Cosine similarity of query_vector against each row of unit_vectors.

    Ollama embeddings are L2-normalized (eval.md § Verifiche su Ollama), so
    cosine reduces to a dot product: no renormalization here.
    """
    if unit_vectors.shape[0] == 0:
        return np.zeros(0)
    return unit_vectors @ np.asarray(query_vector, dtype=np.float64)


def fuse_rankings(*, rankings: Sequence[RankedUnits]) -> list[EvalUnit]:
    """Production's reciprocal rank fusion over any number of ranked lists.

    system=bm25 fuses [doc_bm25, lecture_bm25]; system=dense fuses
    [doc_dense, lecture_dense]; system=hybrid fuses all four in one RRF call
    (plan.md § C2: "BM25 lezioni, BM25 documenti, denso lezioni, denso
    documenti nella stessa fuse_by_rank"), not two 2-way fusions combined. A
    thin, named wrapper so a caller does not need to know each system *is*
    RRF fusion of its own list of candidate rankings.
    """
    return fuse_by_rank(rankings=[list(ranking) for ranking in rankings])


def pool_top_n(
    *, ranked_by_system: Mapping[str, Sequence[EvalUnit]], n: int, seed: int
) -> list[EvalUnit]:
    """Union of each system's top n units, deduplicated, shuffled blind (T014).

    Dedup keeps the first unit seen for a passage_id (ranked_by_system has no
    guaranteed iteration order across Python versions for a plain dict, so
    callers that care should pass one built in a fixed order). The shuffle
    uses its own Random(seed), so it never disturbs any other caller's
    global random state.
    """
    seen: dict[str, EvalUnit] = {}
    for units in ranked_by_system.values():
        for unit in units[:n]:
            seen.setdefault(unit.passage_id, unit)
    pooled = list(seen.values())
    random.Random(seed).shuffle(pooled)
    return pooled


# --------------------------------------------------------------------------
# Gold set / pool JSON <-> dataclass boundary (dict parsing, no file I/O)
# --------------------------------------------------------------------------


def document_ref(raw: dict[str, Any]) -> DocumentRef:
    return DocumentRef(filename=raw["filename"], page=raw["page"])


def lecture_ref(raw: dict[str, Any]) -> LectureRef:
    return LectureRef(job_id=raw["job_id"], start_s=raw["start_s"], end_s=raw["end_s"])


def gold_ref(raw: dict[str, Any]) -> PassageRef:
    if raw["kind"] == "document":
        return document_ref(raw)
    return lecture_ref(raw)


def ref_to_dict(ref: PassageRef) -> dict[str, Any]:
    if isinstance(ref, DocumentRef):
        return {"kind": "document", "filename": ref.filename, "page": ref.page}
    return {
        "kind": "lecture",
        "job_id": ref.job_id,
        "start_s": ref.start_s,
        "end_s": ref.end_s,
    }


def pooling_unit(entry: dict[str, Any]) -> EvalUnit:
    """Reconstruct a placeholder unit from a pool JSON entry (no text needed)."""
    ref = entry["ref"]
    if ref["kind"] == "document":
        return DocUnit(passage_id=entry["passage_id"], text="", ref=document_ref(ref))
    return LectureUnit(passage_id=entry["passage_id"], text="", ref=lecture_ref(ref))


# --------------------------------------------------------------------------
# Ranking helpers that need no index/network access
# --------------------------------------------------------------------------


def safe_model_name(model: str) -> str:
    return model.replace("/", "_").replace(":", "_")


def cache_file_name(model: str) -> str:
    """Vector cache file for a model, tagged with its document prompt.

    Entries are keyed by the raw text, so a changed document prompt must
    land in a new file instead of serving vectors embedded under the old one.
    """
    rendered = format_document(text=PROMPT_PROBE, model=model)
    return f"{safe_model_name(model)}-{content_hash(rendered)[:PROMPT_TAG_LENGTH]}.npz"


def dense_candidates(
    *,
    units: Sequence[EvalUnit],
    cache: Mapping[str, np.ndarray],
    query_vector: Sequence[float],
) -> RankedUnits:
    if not units:
        return []
    matrix = np.stack([cache[content_hash(unit.text)] for unit in units])
    scores = dense_scores(query_vector=query_vector, unit_vectors=matrix)
    return [(-float(score), unit) for unit, score in zip(units, scores, strict=True)]


def score_lookup(rankings: Sequence[RankedUnits]) -> dict[str, float]:
    """passage_id -> native score; first ranking containing it wins."""
    lookup: dict[str, float] = {}
    for ranking in rankings:
        for score, unit in ranking:
            lookup.setdefault(unit.passage_id, score)
    return lookup

"""Embeddings and per-question ranking boundary for scripts/eval_hybrid.py.

T013, specs/004-hybrid-retrieval. The Ollama client, the on-disk vector
cache and the question-level ranking/reporting that reads from a
CourseContext (eval_hybrid_corpus.py). Split out of eval_hybrid.py to keep
each file under the 300-line limit; see eval_hybrid.py's module docstring
for the overall harness framing.
"""

import json
import sys
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from eval_hybrid_corpus import CourseContext, doc_bm25, lecture_bm25
from ollama import Client, ResponseError

from sbobina.embedding_prompts import format_document
from sbobina.embedding_units import (
    EvalUnit,
    content_hash,
)
from sbobina.hybrid_eval import (
    RankedUnits,
    dense_candidates,
    fuse_rankings,
    gold_ref,
    ref_to_dict,
    score_lookup,
)
from sbobina.retrieval import question_to_fts
from sbobina.retrieval_metrics import (
    RankedPassage,
    first_judged_rank,
    first_relevant_rank,
    mean_recall_at_k,
    merge_verdicts,
    mrr_at_k,
)

EMBED_BATCH_SIZE = 32
CONTEXT_EXCEEDED = "exceeds the context length"

Embedder = Callable[[Sequence[str]], list[list[float]]]


# --------------------------------------------------------------------------
# Embeddings: Ollama boundary and on-disk cache
# --------------------------------------------------------------------------


def embed_one_truncating(
    client: Client, model: str, text: str, options: dict[str, Any] | None
) -> list[float]:
    """Embed one text, truncating it only when it exceeds the model context.

    Some passages are numeric tables (log tables in a 1934 statistics
    manual) that exceed embeddinggemma's 2048-token context on their own;
    truncation is counted and reported, never silent.
    """
    try:
        response = client.embed(
            model=model, input=text, truncate=False, options=options
        )
    except ResponseError as error:
        if CONTEXT_EXCEEDED not in str(error):
            raise
        print(f"truncated over-context unit ({len(text)} chars)", file=sys.stderr)
        response = client.embed(model=model, input=text, truncate=True, options=options)
    return list(response.embeddings[0])


def ollama_embedder(
    client: Client, model: str, options: dict[str, Any] | None = None
) -> Embedder:
    def embed(texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = list(texts[start : start + EMBED_BATCH_SIZE])
            try:
                response = client.embed(
                    model=model, input=batch, truncate=False, options=options
                )
            except ResponseError as error:
                if CONTEXT_EXCEEDED not in str(error):
                    raise
                vectors.extend(
                    embed_one_truncating(
                        client=client, model=model, text=text, options=options
                    )
                    for text in batch
                )
                continue
            vectors.extend(list(row) for row in response.embeddings)
        return vectors

    return embed


def load_cache(path: Path) -> dict[str, np.ndarray]:
    if not path.exists():
        return {}
    with np.load(path, allow_pickle=False) as data:
        return dict(zip(data["hashes"].tolist(), data["vectors"], strict=True))


def save_cache(path: Path, cache: dict[str, np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    hashes = np.array(list(cache.keys()))
    vectors = np.array(list(cache.values()), dtype=np.float32)
    np.savez(path, hashes=hashes, vectors=vectors)


def ensure_cached(
    cache: dict[str, np.ndarray],
    units: Sequence[EvalUnit],
    embed: Embedder,
    model: str,
) -> None:
    # Keyed by the raw text: the cache file is per model, so the document
    # prompt (format_document) is fixed within it.
    missing: dict[str, str] = {}
    for unit in units:
        digest = content_hash(unit.text)
        if digest not in cache and digest not in missing:
            missing[digest] = unit.text
    if not missing:
        return
    hashes = list(missing)
    vectors = embed([format_document(text=missing[h], model=model) for h in hashes])
    for digest, vector in zip(hashes, vectors, strict=True):
        cache[digest] = np.asarray(vector, dtype=np.float32)


# --------------------------------------------------------------------------
# Per-question ranking and reporting
# --------------------------------------------------------------------------


def bm25_branch(ctx: CourseContext, question: str) -> list[RankedUnits]:
    match = question_to_fts(question=question)
    if match is None:
        return [[], []]
    return [
        doc_bm25(
            index=ctx.index, scope=ctx.scope, match=match, filenames=ctx.filenames
        ),
        lecture_bm25(
            index=ctx.index,
            scope=ctx.scope,
            match=match,
            lecture_indexes=ctx.lecture_indexes,
        ),
    ]


def dense_branch(
    ctx: CourseContext, cache: dict[str, np.ndarray], query_vector: Sequence[float]
) -> list[RankedUnits]:
    lecture_units = [unit for li in ctx.lecture_indexes.values() for unit in li.units]
    return [
        dense_candidates(units=ctx.doc_units, cache=cache, query_vector=query_vector),
        dense_candidates(units=lecture_units, cache=cache, query_vector=query_vector),
    ]


@dataclass
class RankingResult:
    ranked: list[EvalUnit]
    bm25_lookup: dict[str, float]
    dense_lookup: dict[str, float] | None


@dataclass(frozen=True)
class DenseQuery:
    """The query vector and the corpus vectors it is scored against."""

    cache: dict[str, np.ndarray]
    vector: Sequence[float]


def rank_question(
    *, system: str, ctx: CourseContext, question: str, dense: DenseQuery | None
) -> RankingResult:
    """Fused ranking plus score lookups for reporting (bm25 native, dense cosine)."""
    bm25_rankings = bm25_branch(ctx=ctx, question=question)
    bm25_lookup = score_lookup(bm25_rankings)
    if system == "bm25":
        return RankingResult(
            ranked=fuse_rankings(rankings=bm25_rankings),
            bm25_lookup=bm25_lookup,
            dense_lookup=None,
        )
    if dense is None:
        raise ValueError(f"system {system!r} needs a query vector")
    dense_rankings = dense_branch(ctx=ctx, cache=dense.cache, query_vector=dense.vector)
    dense_lookup = {
        passage_id: -score for passage_id, score in score_lookup(dense_rankings).items()
    }
    rankings = (
        dense_rankings if system == "dense" else [*bm25_rankings, *dense_rankings]
    )
    return RankingResult(
        ranked=fuse_rankings(rankings=rankings),
        bm25_lookup=bm25_lookup,
        dense_lookup=dense_lookup,
    )


def build_question_record(
    *, item: dict[str, Any], system: str, result: RankingResult, k: int
) -> dict[str, Any]:
    gold = [gold_ref(raw) for raw in item["references"]]
    rank = first_relevant_rank(
        ranked_refs=[unit.ref for unit in result.ranked], gold_refs=gold
    )
    top_k: list[dict[str, Any]] = []
    for position, unit in enumerate(result.ranked[:k], start=1):
        entry: dict[str, Any] = {
            "rank": position,
            "passage_id": unit.passage_id,
            "ref": ref_to_dict(unit.ref),
            "bm25_score": result.bm25_lookup.get(unit.passage_id),
        }
        if result.dense_lookup is not None:
            entry["cosine"] = result.dense_lookup.get(unit.passage_id)
        top_k.append(entry)
    return {
        "id": item["id"],
        "type": item["type"],
        "course": item["course"],
        "system": system,
        "first_relevant_rank": rank,
        "top_k": top_k,
    }


def load_verdicts(judging_dir: Path) -> dict[str, dict[str, int]]:
    # glob() on a missing directory yields nothing: without this check a typo
    # in --judgments would silently score against the bare gold.
    files = sorted(judging_dir.glob("verdicts-*.json"))
    if not files:
        raise FileNotFoundError(f"no verdicts-*.json in {judging_dir}")
    return merge_verdicts(
        verdict_files=[json.loads(path.read_text(encoding="utf-8")) for path in files]
    )


def apply_judgments(
    records: list[dict[str, Any]],
    gold_by_id: dict[str, dict[str, Any]],
    votes: dict[str, dict[str, int]],
) -> list[dict[str, Any]]:
    """Re-rank hits with the blind judgments: a full-answer vote counts too.

    Only the saved top_k is visible here, so --k must cover the cutoffs read.
    """
    judged = []
    for record in records:
        ranked = [
            RankedPassage(passage_id=entry["passage_id"], ref=gold_ref(entry["ref"]))
            for entry in record["top_k"]
        ]
        gold = [gold_ref(raw) for raw in gold_by_id[record["id"]]["references"]]
        rank = first_judged_rank(
            ranked=ranked, gold_refs=gold, votes=votes.get(record["id"], {})
        )
        judged.append({**record, "first_relevant_rank": rank})
    return judged


def print_summary(records: list[dict[str, Any]]) -> None:
    ranks_by_group: dict[str, list[int | None]] = defaultdict(list)
    for record in records:
        ranks_by_group[record["type"]].append(record["first_relevant_rank"])
        ranks_by_group["all"].append(record["first_relevant_rank"])
    for group, ranks in ranks_by_group.items():
        mrr10 = sum(mrr_at_k(rank=rank, k=10) for rank in ranks) / len(ranks)
        print(
            f"{group}: n={len(ranks)} recall@5={mean_recall_at_k(ranks=ranks, k=5):.2f} "
            f"recall@8={mean_recall_at_k(ranks=ranks, k=8):.2f} mrr@10={mrr10:.3f}"
        )

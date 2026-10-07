"""Measure hybrid retrieval quality against the gold set (T013, specs/004-hybrid-retrieval).

Usage::

    uv run python scripts/eval_hybrid.py --system bm25 --out out/bm25.json
    uv run python scripts/eval_hybrid.py --system dense --model qwen3-embedding:0.6b \\
        --out out/dense.json
    uv run python scripts/eval_hybrid.py --system hybrid --model qwen3-embedding:0.6b \\
        --query-instruction on --out out/hybrid.json
    uv run python scripts/eval_hybrid.py --pool out/bm25.json out/dense.json \\
        out/hybrid.json --out out/pool.json

``--system bm25`` never touches Ollama. ``dense``/``hybrid`` batch-embed the
corpus once per model, cached on disk by content hash under
``data/eval/retrieval-hybrid/cache/<model>.npz`` (so a repeated run, or a
second variant of the same model, never re-embeds unchanged text), and embed
the query fresh every call with ``options.num_gpu=0`` (plan.md Dis.5 option
A: the query runs on CPU so the resident chat model is never swapped out).
All logic that does not need the index, the job store or Ollama lives in
``sbobina.hybrid_eval`` (pure, unit-tested); the course corpus and Ollama/
cache/ranking I/O live in ``eval_hybrid_corpus.py`` and ``eval_hybrid_io.py``
(sibling modules, same directory); this script is the CLI entry point.

Document and lecture units are the shared candidate space BM25 and dense
both rank: a document unit is the FTS passage production's bm25 already
ranks; a lecture unit is a ~250-word ``partition_lecture_segments`` window
(not the raw 10-30 word Whisper segment BM25 matches), so a raw-segment
BM25 hit is first projected onto the window containing it
(``aggregate_lecture_hits_to_windows``). This is plan.md Dis.3 option B,
scoped to this harness only: production's default (T016-measured) stays
option A. See specs/004-hybrid-retrieval/eval.md.
"""

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
from eval_hybrid_corpus import CourseContext, build_course_context
from eval_hybrid_io import (
    DenseQuery,
    Embedder,
    apply_judgments,
    build_question_record,
    ensure_cached,
    load_cache,
    load_verdicts,
    ollama_embedder,
    print_summary,
    rank_question,
    save_cache,
)
from ollama import Client

from sbobina.embedding_prompts import apply_query_instruction
from sbobina.hybrid_eval import (
    EvalUnit,
    cache_file_name,
    pool_top_n,
    pooling_unit,
    ref_to_dict,
)
from sbobina.web.job_store import JobStore
from sbobina.web.search_index import SearchIndex
from sbobina.web.search_service import search_session

DEFAULT_DATA_DIR = Path("data/eval/retrieval-hybrid/corpus")
DEFAULT_GOLD = Path("data/eval/retrieval-hybrid/gold.json")
DEFAULT_CACHE_DIR = Path("data/eval/retrieval-hybrid/cache")
DEFAULT_OLLAMA_HOST = "http://localhost:11434"


def load_gold(path: Path) -> list[dict[str, Any]]:
    items = json.loads(path.read_text(encoding="utf-8"))["items"]
    return cast(list[dict[str, Any]], items)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--system", choices=["bm25", "dense", "hybrid"])
    parser.add_argument("--model")
    parser.add_argument("--query-instruction", choices=["on", "off"], default="off")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pool", nargs="+", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--judgments", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.pool is None:
        if args.system is None:
            parser.error("--system e' richiesto senza --pool")
        if args.system != "bm25" and not args.model:
            parser.error(f"--model e' richiesto per --system {args.system}")
    return args


def run_pool(args: argparse.Namespace) -> int:
    ranked_by_system: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(dict)
    for path in args.pool:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for record in payload["records"]:
            ranked_by_system[record["id"]][payload["system"]] = record["top_k"]
    pooled_questions = []
    for question_id, by_system in ranked_by_system.items():
        units_by_system: dict[str, list[EvalUnit]] = {
            system: [pooling_unit(entry) for entry in top_k]
            for system, top_k in by_system.items()
        }
        pooled = pool_top_n(ranked_by_system=units_by_system, n=10, seed=args.seed)
        pooled_questions.append(
            {
                "id": question_id,
                "pool": [
                    {"passage_id": unit.passage_id, "ref": ref_to_dict(unit.ref)}
                    for unit in pooled
                ],
            }
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"questions": pooled_questions}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"pool: {len(pooled_questions)} domande scritte in {args.out}")
    return 0


def build_embedders(
    args: argparse.Namespace,
) -> tuple[Embedder | None, Embedder | None]:
    """Corpus embedder on GPU and query embedder on CPU; none for BM25."""
    if args.system == "bm25":
        return None, None
    client = Client(host=DEFAULT_OLLAMA_HOST)
    corpus_embed = ollama_embedder(client=client, model=args.model)
    query_embed = ollama_embedder(
        client=client, model=args.model, options={"num_gpu": 0}
    )
    return corpus_embed, query_embed


@dataclass(frozen=True)
class Embeddings:
    """Corpus vectors (filled per course on first use) and the two embedders."""

    cache: dict[str, np.ndarray]
    corpus: Embedder | None
    query: Embedder | None
    model: str | None


def open_course(
    store: JobStore, index: SearchIndex, course: str, embeddings: Embeddings
) -> CourseContext:
    ctx = build_course_context(store=store, index=index, key=course)
    if embeddings.corpus is not None and embeddings.model is not None:
        ensure_cached(
            cache=embeddings.cache,
            units=ctx.all_units(),
            embed=embeddings.corpus,
            model=embeddings.model,
        )
    return ctx


def embed_question(
    args: argparse.Namespace, question: str, embeddings: Embeddings
) -> list[float] | None:
    if embeddings.query is None:
        return None
    text = apply_query_instruction(
        question=question, enabled=args.query_instruction == "on", model=args.model
    )
    [query_vector] = embeddings.query([text])
    return query_vector


def rank_item(
    args: argparse.Namespace,
    item: dict[str, Any],
    ctx: CourseContext,
    embeddings: Embeddings,
) -> dict[str, Any]:
    vector = embed_question(args=args, question=item["question"], embeddings=embeddings)
    dense = (
        None if vector is None else DenseQuery(cache=embeddings.cache, vector=vector)
    )
    result = rank_question(
        system=args.system, ctx=ctx, question=item["question"], dense=dense
    )
    return build_question_record(item=item, system=args.system, result=result, k=args.k)


def rank_gold(
    args: argparse.Namespace, gold: list[dict[str, Any]], embeddings: Embeddings
) -> list[dict[str, Any]]:
    store = JobStore(data_dir=args.data_dir)
    with search_session(store=store, path=args.data_dir / "search.sqlite3") as index:
        contexts = {
            course: open_course(
                store=store, index=index, course=course, embeddings=embeddings
            )
            for course in sorted({item["course"] for item in gold})
        }
        return [
            rank_item(
                args=args,
                item=item,
                ctx=contexts[item["course"]],
                embeddings=embeddings,
            )
            for item in gold
        ]


def write_records(args: argparse.Namespace, records: list[dict[str, Any]]) -> None:
    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"system": args.system, "model": args.model, "records": records}
    args.out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def run_system(args: argparse.Namespace) -> int:
    corpus_embed, query_embed = build_embedders(args=args)
    cache_path = (
        DEFAULT_CACHE_DIR / cache_file_name(model=args.model) if args.model else None
    )
    cache = load_cache(path=cache_path) if cache_path and corpus_embed else {}
    embeddings = Embeddings(
        cache=cache, corpus=corpus_embed, query=query_embed, model=args.model
    )
    gold = load_gold(path=args.gold)
    records = rank_gold(args=args, gold=gold, embeddings=embeddings)
    if args.judgments is not None:
        records = apply_judgments(
            records=records,
            gold_by_id={item["id"]: item for item in gold},
            votes=load_verdicts(judging_dir=args.judgments),
        )
    if cache_path is not None and cache:
        save_cache(path=cache_path, cache=cache)
    write_records(args=args, records=records)
    print_summary(records=records)
    return 0


def main() -> int:
    args = parse_args(sys.argv[1:])
    if args.pool is not None:
        return run_pool(args=args)
    return run_system(args=args)


if __name__ == "__main__":
    sys.exit(main())

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from time import monotonic
from typing import Any

from eval_hybrid_corpus import CourseContext, build_course_context
from ollama import Client

from sbobina import ollama_embed
from sbobina.hybrid_eval import gold_ref, lecture_window_ref, ref_to_dict
from sbobina.retrieval import DocumentSource, RetrievalSource, RetrievedPassage
from sbobina.retrieval_metrics import DocumentRef, PassageRef, first_relevant_rank
from sbobina.settings import Settings
from sbobina.web.course_retrieval import WindowedQuery, retrieve_windows_with_report
from sbobina.web.dense_factory import VECTOR_FILENAME, DenseRuntime, dense_for_process
from sbobina.web.job_store import JobStore
from sbobina.web.search_service import search_session
from sbobina.web.vector_reconcile import (
    CourseEmbedding,
    EmbeddingConfig,
    EmbeddingProgress,
    embed_course,
)
from sbobina.web.vector_store import VectorStore

RETRIEVAL_BUDGET_WORDS = 50_000


def resolve_ref(source: RetrievalSource, ctx: CourseContext) -> PassageRef:
    if isinstance(source, DocumentSource):
        return DocumentRef(filename=ctx.filenames[source.doc_id], page=source.page)
    lecture = ctx.lecture_indexes[source.job_id]
    return lecture_window_ref(
        segment_index=source.segment_index,
        positions=lecture.positions,
        spans=lecture.spans,
        units=lecture.units,
    )


def build_record(
    item: dict[str, Any], passages: list[RetrievedPassage], ctx: CourseContext, k: int
) -> dict[str, Any]:
    refs = [resolve_ref(source=passage.source, ctx=ctx) for passage in passages]
    rank = first_relevant_rank(
        ranked_refs=refs, gold_refs=[gold_ref(raw) for raw in item["references"]]
    )
    return {
        "id": item["id"],
        "type": item["type"],
        "course": item["course"],
        "system": "production",
        "first_relevant_rank": rank,
        "top_k": [
            {
                "rank": position,
                "passage_id": passage.passage_id,
                "ref": ref_to_dict(ref),
            }
            for position, (passage, ref) in enumerate(
                zip(passages[:k], refs[:k], strict=True), start=1
            )
        ],
    }


def print_progress(progress: EmbeddingProgress, course: str) -> None:
    print(
        f"{course}: {progress.processed}/{progress.total} unità, "
        f"{progress.units_per_second:.2f} unità/s, troncati={progress.truncated}",
        file=sys.stderr,
    )


def index_course(context: CourseEmbedding, course: str) -> None:
    started = monotonic()
    result = embed_course(
        context=context,
        course_key=course,
        progress=partial(print_progress, course=course),
    )
    print(
        f"{course}: indicizzazione {monotonic() - started:.1f}s, "
        f"{result.units_per_second:.2f} unità/s, "
        f"unità={result.processed}/{result.total}, troncati={result.truncated}",
        file=sys.stderr,
    )


def index_courses(data_dir: Path, courses: list[str], settings: Settings) -> None:
    status = ollama_embed.model_status(
        host=settings.ollama_host,
        model=settings.embedding_model,
        timeout_s=settings.embedding_timeout_s,
    )
    client = Client(host=settings.ollama_host)
    model = settings.embedding_model

    def embedder(
        texts: Sequence[ollama_embed.EmbeddingInput],
    ) -> list[ollama_embed.EmbeddedText]:
        return ollama_embed.embed_texts(
            client=client, model=model, texts=texts, mode="document"
        )

    with closing(VectorStore(path=data_dir.resolve() / VECTOR_FILENAME)) as vectors:
        context = CourseEmbedding(
            store=JobStore(data_dir=data_dir),
            vectors=vectors,
            embedding=EmbeddingConfig(
                model=settings.embedding_model, status=status, embedder=embedder
            ),
        )
        for course in courses:
            index_course(context=context, course=course)


@dataclass(frozen=True)
class ProductionSession:
    store: JobStore
    runtime: DenseRuntime


def rank_item(
    args: argparse.Namespace,
    item: dict[str, Any],
    ctx: CourseContext,
    session: ProductionSession,
) -> dict[str, Any]:
    passages, report = retrieve_windows_with_report(
        store=session.store,
        index=ctx.index,
        query=WindowedQuery(
            scope=ctx.scope,
            question=item["question"],
            budget_words=RETRIEVAL_BUDGET_WORDS,
        ),
        dense=session.runtime.ranker,
    )
    payload = session.runtime.metadata(report=report)
    return {
        **build_record(item=item, passages=passages, ctx=ctx, k=args.k),
        "mode": payload["mode"],
        "reason": payload["reason"],
    }


def rank_gold(
    args: argparse.Namespace, gold: list[dict[str, Any]]
) -> tuple[str, list[dict[str, Any]]]:
    settings = Settings()
    if args.model is not None:
        settings = settings.model_copy(update={"embedding_model": args.model})
    store = JobStore(data_dir=args.data_dir)
    courses = sorted({item["course"] for item in gold})
    if args.index:
        index_courses(data_dir=args.data_dir, courses=courses, settings=settings)
    runtime = dense_for_process(settings=settings, data_dir=args.data_dir)
    session = ProductionSession(store=store, runtime=runtime)
    with search_session(store=store, path=args.data_dir / "search.sqlite3") as index:
        contexts = {
            course: build_course_context(store=store, index=index, key=course)
            for course in courses
        }
        records = [
            rank_item(
                args=args, item=item, ctx=contexts[item["course"]], session=session
            )
            for item in gold
        ]
    return settings.embedding_model, records


def print_modes(records: list[dict[str, Any]]) -> None:
    counts = Counter((record["mode"], record["reason"]) for record in records)
    for (mode, reason), count in counts.items():
        print(f"mode={mode} reason={reason}: n={count}")

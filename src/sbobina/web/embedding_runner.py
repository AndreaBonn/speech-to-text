import json
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from pathlib import Path

from ollama import Client

from sbobina.ollama_embed import embed_texts, model_status
from sbobina.runtime_config import runtime_settings
from sbobina.settings import Settings, settings
from sbobina.web import dense_factory
from sbobina.web.embedding_store import (
    EmbeddingStatus,
    finish_embed,
    load_embed,
    save_embed,
)
from sbobina.web.job_store import JobStore
from sbobina.web.vector_reconcile import (
    CourseEmbedding,
    EmbeddingConfig,
    EmbeddingProgress,
    count_missing_units,
    embed_course,
    embedding_model_key,
)

COURSE_FILENAME = "course.json"
# T032/T033 measured 0.85-2.64 units/s with qwen3-embedding:8b.
EMBEDDING_UNITS_PER_SECOND = 1.7
# T033 observed a 117.8 s batch including model reload; query timeouts are shorter.
EMBEDDING_BATCH_TIMEOUT_S = 180.0


def _course_key(course_dir: Path) -> str:
    return str(
        json.loads((course_dir / COURSE_FILENAME).read_text(encoding="utf-8"))["key"]
    )


def _write_progress(course_dir: Path, update: EmbeddingProgress) -> None:
    record = load_embed(course_dir=course_dir)
    if record is not None and record.status == EmbeddingStatus.RUNNING:
        save_embed(
            course_dir=course_dir,
            record=replace(record, processed=update.processed, total=update.total),
        )


def run_embed(course_dir: Path, embed: Callable[..., EmbeddingProgress]) -> None:
    """Run an injected course embedder, persisting each committed batch's progress.

    Parameters
    ----------
    course_dir : Path
        Registered course directory, with a RUNNING embedding record.
    embed : Callable
        Accepts course_key and progress keywords; failures propagate to the supervisor.
    """
    result = embed(
        course_key=_course_key(course_dir=course_dir),
        progress=lambda update: _write_progress(course_dir=course_dir, update=update),
    )
    _write_progress(course_dir=course_dir, update=result)
    finish_embed(course_dir=course_dir, status=EmbeddingStatus.DONE)


def estimate_embed_seconds(course_dir: Path) -> float:
    data_dir = course_dir.parent.parent
    running = runtime_settings(settings=settings)
    status = model_status(
        host=running.ollama_host,
        model=running.embedding_model,
        timeout_s=running.embedding_timeout_s,
    )
    missing = count_missing_units(
        store=JobStore(data_dir=data_dir),
        vectors=dense_factory.vector_store_for_process(data_dir=data_dir),
        model_key=embedding_model_key(model=running.embedding_model, status=status),
        course_key=_course_key(course_dir=course_dir),
    )
    return missing / EMBEDDING_UNITS_PER_SECOND


def _embedding_config(settings: Settings) -> EmbeddingConfig:
    client = Client(
        host=settings.ollama_host,
        timeout=max(settings.embedding_timeout_s, EMBEDDING_BATCH_TIMEOUT_S),
    )
    status = model_status(
        host=settings.ollama_host,
        model=settings.embedding_model,
        timeout_s=settings.embedding_timeout_s,
    )
    return EmbeddingConfig(
        model=settings.embedding_model,
        status=status,
        embedder=lambda texts: embed_texts(
            client=client,
            model=settings.embedding_model,
            texts=texts,
            mode="document",
        ),
    )


def run_embed_stage(course_dir: Path) -> None:
    data_dir = course_dir.parent.parent
    embedding = _embedding_config(settings=runtime_settings(settings=settings))
    context = CourseEmbedding(
        store=JobStore(data_dir=data_dir),
        vectors=dense_factory.vector_store_for_process(data_dir=data_dir),
        embedding=embedding,
    )
    run_embed(course_dir=course_dir, embed=partial(embed_course, context=context))

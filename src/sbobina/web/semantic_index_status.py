from dataclasses import asdict
from pathlib import Path

from fastapi.encoders import jsonable_encoder
from pydantic import JsonValue

from sbobina import ollama_embed
from sbobina.course_registry import CourseRecord, iter_courses
from sbobina.embedding_prompts import EMBEDDING_THRESHOLDS
from sbobina.settings import Settings
from sbobina.web.dense_factory import VECTOR_FILENAME
from sbobina.web.embedding_store import EmbeddingStatus, load_embed
from sbobina.web.job_store import JobStore
from sbobina.web.vector_reconcile import count_missing_units, embedding_model_key
from sbobina.web.vector_store import VectorStore

# The Settings page waits on these probes: a hung Ollama must not hold it for
# the full embedding timeout. A refused local connection fails at once anyway.
STATUS_PROBE_TIMEOUT_S = 2.0

# Conservative estimate against 0.85-1.71 and 2.6 units/s measured in
# specs/004-hybrid-retrieval/eval.md; UI estimates must not promise peak throughput.
ESTIMATED_UNITS_PER_SECOND = 1.0
RECOMMENDED_EMBEDDING_MODEL = "qwen3-embedding:8b"


def _model_view(settings: Settings) -> tuple[dict[str, JsonValue], str | None]:
    view: dict[str, JsonValue] = {
        "model": settings.embedding_model,
        "semantic_search": settings.semantic_search,
        "measured": settings.embedding_model in EMBEDDING_THRESHOLDS,
    }
    try:
        status = ollama_embed.model_status(
            host=settings.ollama_host,
            model=settings.embedding_model,
            timeout_s=STATUS_PROBE_TIMEOUT_S,
        )
    except ollama_embed.EmbeddingUnavailableError as error:
        return view | {
            "installed": False,
            "dimensions": None,
            "reason": error.reason,
        }, None
    key = embedding_model_key(model=settings.embedding_model, status=status)
    return view | {
        "installed": True,
        "dimensions": status.dimensions,
        "reason": None,
    }, key


def _run_view(directory: Path) -> dict[str, JsonValue]:
    run = load_embed(course_dir=directory)
    active = run is not None and run.status in (
        EmbeddingStatus.QUEUED,
        EmbeddingStatus.RUNNING,
    )
    return {
        "run": jsonable_encoder(run),
        "queued_action": "embed" if active else None,
        "last_indexed_at": run.last_indexed_at.isoformat()
        if run is not None and run.last_indexed_at is not None
        else None,
    }


def _coverage_view(
    store: JobStore,
    vectors: VectorStore,
    course_key: str,
    model_key: str | None,
) -> dict[str, JsonValue]:
    if model_key is None:
        return {"coverage": None, "missing_units": None, "estimated_seconds": None}
    missing = count_missing_units(
        store=store,
        vectors=vectors,
        model_key=model_key,
        course_key=course_key,
    )
    coverage = vectors.coverage(course=course_key, model_key=model_key)
    return {
        "coverage": asdict(coverage),
        "missing_units": missing,
        "estimated_seconds": missing / ESTIMATED_UNITS_PER_SECOND,
    }


def _course_view(
    store: JobStore,
    vectors: VectorStore,
    course: CourseRecord,
    model_key: str | None,
) -> dict[str, JsonValue]:
    return {
        "key": course.key,
        "label": course.label,
        **_coverage_view(
            store=store, vectors=vectors, course_key=course.key, model_key=model_key
        ),
        **_run_view(directory=store.courses_dir / course.id),
    }


def semantic_index_status(
    *,
    settings: Settings,
    store: JobStore,
    vectors: VectorStore,
) -> dict[str, JsonValue]:
    view, key = _model_view(settings=settings)
    # data_version() refreshes the rebuild marker another process may have cleared.
    vectors.data_version()
    return view | {
        "rebuild_needed": vectors.rebuild_needed,
        "model_change_pending": None
        if key is None
        else vectors.has_other_models(model_key=key),
        "courses": [
            _course_view(store=store, vectors=vectors, course=course, model_key=key)
            for course in iter_courses(courses_dir=store.courses_dir)
        ],
        "size_bytes": (store.jobs_dir.parent / VECTOR_FILENAME).stat().st_size,
    }


def embedding_models_view(settings: Settings) -> dict[str, JsonValue]:
    try:
        names = ollama_embed.list_embedding_models(
            host=settings.ollama_host,
            timeout_s=STATUS_PROBE_TIMEOUT_S,
        )
    except ollama_embed.EmbeddingUnavailableError as error:
        return {"status": error.reason, "models": []}
    return {
        "status": "available",
        "models": [
            {
                "model": name,
                "recommended": name == RECOMMENDED_EMBEDDING_MODEL,
                "measured": name in EMBEDDING_THRESHOLDS,
            }
            for name in names
        ],
    }

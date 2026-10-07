import logging
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import monotonic

from sbobina.embedding_prompts import (
    EMBEDDING_PROMPT_VERSION,
    format_document_for_production,
)
from sbobina.embedding_units import build_lecture_units, content_hash
from sbobina.lecture_windows import WINDOW_WORDS
from sbobina.models import load_transcript
from sbobina.ollama_embed import (
    EMBED_BATCH_SIZE,
    EMBEDDING_NUM_CTX,
    EmbeddedText,
    EmbeddingInput,
    ModelStatus,
    validate_dimensions,
)
from sbobina.search_text import passages_from_transcript
from sbobina.web.course_retrieval import course_scope
from sbobina.web.document_store import DOCUMENT_FILENAME
from sbobina.web.job_store import JobStore
from sbobina.web.search_service import (
    preferred_transcript,
    read_document_passages,
    ready_document_state,
)
from sbobina.web.vector_store import Coverage, StoredVector, VectorStore

logger = logging.getLogger(__name__)


def embedding_model_key(model: str, status: ModelStatus) -> str:
    """Identify the model weights and all production embedding settings."""
    return (
        f"{model}@{EMBEDDING_PROMPT_VERSION}:{status.digest}"
        f":{status.dimensions}:{EMBEDDING_NUM_CTX}"
    )


@dataclass(frozen=True)
class EmbeddingConfig:
    model: str
    status: ModelStatus
    embedder: Callable[[Sequence[EmbeddingInput]], list[EmbeddedText]]

    @property
    def model_key(self) -> str:
        return embedding_model_key(model=self.model, status=self.status)


@dataclass(frozen=True)
class CourseEmbedding:
    store: JobStore
    vectors: VectorStore
    embedding: EmbeddingConfig


@dataclass(frozen=True)
class EmbeddingProgress:
    """Covered units (including cache), truncations and newly covered units/s."""

    processed: int
    total: int
    truncated: int
    units_per_second: float


def _lecture_inputs(store: JobStore, job_id: str) -> list[EmbeddingInput]:
    preferred = preferred_transcript(directory=store.jobs_dir / job_id)
    if preferred is None:
        return []
    transcript = load_transcript(path=preferred[0])
    passages = passages_from_transcript(transcript=transcript)
    _, units = build_lecture_units(
        job_id=job_id,
        segments=passages,
        segment_ends=[transcript.segments[item.segment_index].end for item in passages],
        window_words=WINDOW_WORDS,
    )
    return [
        EmbeddingInput(text=unit.text, passage_id=unit.passage_id) for unit in units
    ]


def _course_inputs(store: JobStore, course_key: str) -> list[EmbeddingInput]:
    scope = course_scope(store=store, key=course_key)
    inputs = [
        item
        for job_id in sorted(scope.job_ids)
        for item in _lecture_inputs(store=store, job_id=job_id)
    ]
    if not scope.course_id:
        return inputs
    documents_dir = store.courses_dir / scope.course_id / "documents"
    for path in sorted(documents_dir.glob(f"*/{DOCUMENT_FILENAME}")):
        if ready_document_state(document_path=path) is None:
            continue
        passages = read_document_passages(doc_dir=path.parent, doc_id=path.parent.name)
        inputs.extend(
            EmbeddingInput(text=item.text, passage_id=item.passage_id)
            for item in passages or []
        )
    return inputs


def _write_batch(context: CourseEmbedding, batch: Sequence[EmbeddingInput]) -> None:
    formatted = [
        EmbeddingInput(
            text=format_document_for_production(
                model=context.embedding.model, text=item.text
            ),
            passage_id=item.passage_id,
        )
        for item in batch
    ]
    embedded = context.embedding.embedder(formatted)
    validate_dimensions(
        embedded=embedded, expected_dimensions=context.embedding.status.dimensions
    )
    vectors = [
        StoredVector(
            text_sha256=content_hash(item.text),
            vector=tuple(result.vector),
            truncated=result.truncated,
        )
        for item, result in zip(batch, embedded, strict=True)
    ]
    context.vectors.put_vectors(model_key=context.embedding.model_key, vectors=vectors)


def _progress(coverage: Coverage, initial: int, started: float) -> EmbeddingProgress:
    elapsed = monotonic() - started
    return EmbeddingProgress(
        processed=coverage.embedded,
        total=coverage.total,
        truncated=coverage.truncated,
        units_per_second=(coverage.embedded - initial) / elapsed
        if elapsed > 0
        else 0.0,
    )


def _sync_pending(context: CourseEmbedding, course_key: str) -> list[EmbeddingInput]:
    units = _course_inputs(store=context.store, course_key=course_key)
    hashes = {item.passage_id: content_hash(item.text) for item in units}
    context.vectors.sync_units(course=course_key, units=hashes)
    key = context.embedding.model_key
    missing = context.vectors.missing_hashes(model_key=key, hashes=set(hashes.values()))
    pending = {
        hashes[item.passage_id]: item
        for item in units
        if hashes[item.passage_id] in missing
    }
    return list(pending.values())


def count_missing_units(
    store: JobStore, vectors: VectorStore, model_key: str, course_key: str
) -> int:
    """Count current uncached units, without altering manifests or embedding text."""
    units = _course_inputs(store=store, course_key=course_key)
    hashes = [content_hash(item.text) for item in units]
    missing = vectors.missing_hashes(model_key=model_key, hashes=set(hashes))
    return sum(text_hash in missing for text_hash in hashes)


def embed_course(
    context: CourseEmbedding,
    course_key: str,
    progress: Callable[[EmbeddingProgress], None],
) -> EmbeddingProgress:
    """Reconcile disk units; propagate failures, preserving completed batches.

    Parameters
    ----------
    context : CourseEmbedding
        Shared dependencies, reused across courses.
    course_key : str
        Normalized key, also identifying the vector manifest.
    progress : Callable
        Receives initial coverage and every committed batch's progress.
    """
    started = monotonic()
    pending = _sync_pending(context=context, course_key=course_key)
    key = context.embedding.model_key
    coverage = context.vectors.coverage(course=course_key, model_key=key)
    initial = coverage.embedded
    update = _progress(coverage=coverage, initial=initial, started=started)
    progress(update)
    for start in range(0, len(pending), EMBED_BATCH_SIZE):
        _write_batch(context=context, batch=pending[start : start + EMBED_BATCH_SIZE])
        coverage = context.vectors.coverage(course=course_key, model_key=key)
        update = _progress(coverage=coverage, initial=initial, started=started)
        progress(update)
    _purge_old_models(vectors=context.vectors, model_key=key)
    return update


def _purge_old_models(*, vectors: VectorStore, model_key: str) -> None:
    # The new vectors are already committed: a busy VACUUM must not fail the run,
    # and the next completed run retries the purge.
    try:
        vectors.purge_obsolete_models(model_key=model_key)
    except sqlite3.Error:
        logger.warning("Old embedding models not purged", exc_info=True)

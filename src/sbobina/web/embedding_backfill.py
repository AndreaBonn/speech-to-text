import logging
from dataclasses import dataclass

from sbobina.course_registry import iter_courses
from sbobina.ollama_embed import ModelStatus
from sbobina.settings import settings
from sbobina.web.embedding_supervisor import submit_embed_item
from sbobina.web.errors import ConflictError
from sbobina.web.job_models import WorkItem
from sbobina.web.job_store import JobStore
from sbobina.web.vector_reconcile import count_missing_units, embedding_model_key
from sbobina.web.vector_store import VectorStore

logger = logging.getLogger(__name__)
ALREADY_QUEUED = "EMBED_ALREADY_QUEUED"


@dataclass(frozen=True)
class BackfillResult:
    model_change_pending: bool
    items: tuple[WorkItem, ...]


def _enqueue_course(*, store: JobStore, course_key: str) -> tuple[WorkItem, ...]:
    try:
        _, item = submit_embed_item(store=store, course_key=course_key)
        return (item,)
    except ConflictError as error:
        if error.code != ALREADY_QUEUED:
            raise
        logger.debug("Embedding already pending for course %s", course_key)
        return ()


def enqueue_backfill(
    *,
    store: JobStore,
    vectors: VectorStore,
    status: ModelStatus,
    confirm_model_change: bool = False,
) -> BackfillResult:
    """Persist queued runs for courses with unindexed units, gating model changes.

    Parameters
    ----------
    store, vectors : JobStore, VectorStore
        Shared registry and process-local vector store.
    status, confirm_model_change : ModelStatus, bool
        Installed model identity, checked by the caller, and explicit rebuild
        authorization.
    """
    key = embedding_model_key(model=settings.embedding_model, status=status)
    if vectors.has_other_models(model_key=key) and not confirm_model_change:
        return BackfillResult(model_change_pending=True, items=())
    items: list[WorkItem] = []
    for course in iter_courses(courses_dir=store.courses_dir):
        # Units on disk, not the manifest: a never-indexed course has no manifest
        # and a stale one misses text added since the last run.
        missing = count_missing_units(
            store=store, vectors=vectors, model_key=key, course_key=course.key
        )
        if missing:
            items.extend(_enqueue_course(store=store, course_key=course.key))
    return BackfillResult(model_change_pending=False, items=tuple(items))

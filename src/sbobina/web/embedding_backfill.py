import logging
from dataclasses import dataclass

from sbobina.course_registry import iter_courses
from sbobina.ollama_embed import ModelStatus
from sbobina.runtime_config import runtime_settings
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


class BackfillEnqueueError(OSError):
    def __init__(self, *, items: tuple[WorkItem, ...]) -> None:
        super().__init__("Backfill enqueue failed after partial progress")
        self.items = items


def _enqueue_course(*, store: JobStore, course_key: str) -> tuple[WorkItem, ...]:
    try:
        _, item = submit_embed_item(store=store, course_key=course_key)
        return (item,)
    except ConflictError as error:
        if error.code != ALREADY_QUEUED:
            raise
        logger.debug("Embedding already pending for course %s", course_key)
        return ()


@dataclass(frozen=True)
class BackfillPlan:
    model_change_pending: bool
    course_keys: tuple[str, ...]


def plan_backfill(
    *,
    store: JobStore,
    vectors: VectorStore,
    status: ModelStatus,
    confirm_model_change: bool = False,
) -> BackfillPlan:
    """Find courses with unindexed units, reading text only; nothing is queued.

    Parameters
    ----------
    store, vectors : JobStore, VectorStore
        Shared registry and process-local vector store.
    status, confirm_model_change : ModelStatus, bool
        Installed model identity, checked by the caller, and explicit rebuild
        authorization.
    """
    model = status.model or runtime_settings(settings=settings).embedding_model
    key = embedding_model_key(model=model, status=status)
    if vectors.has_other_models(model_key=key) and not confirm_model_change:
        return BackfillPlan(model_change_pending=True, course_keys=())
    # Units on disk, not the manifest: a never-indexed course has no manifest
    # and a stale one misses text added since the last run.
    keys = tuple(
        course.key
        for course in iter_courses(courses_dir=store.courses_dir)
        if count_missing_units(
            store=store, vectors=vectors, model_key=key, course_key=course.key
        )
    )
    return BackfillPlan(model_change_pending=False, course_keys=keys)


def enqueue_planned(*, store: JobStore, plan: BackfillPlan) -> BackfillResult:
    """Persist one queued run per planned course; partial progress travels on error."""
    if plan.model_change_pending:
        return BackfillResult(model_change_pending=True, items=())
    items: list[WorkItem] = []
    try:
        for course_key in plan.course_keys:
            items.extend(_enqueue_course(store=store, course_key=course_key))
    except Exception as error:
        raise BackfillEnqueueError(items=tuple(items)) from error
    return BackfillResult(model_change_pending=False, items=tuple(items))


def enqueue_backfill(
    *,
    store: JobStore,
    vectors: VectorStore,
    status: ModelStatus,
    confirm_model_change: bool = False,
) -> BackfillResult:
    """Plan and queue in one step, for callers without a live queue lock (CLI)."""
    plan = plan_backfill(
        store=store,
        vectors=vectors,
        status=status,
        confirm_model_change=confirm_model_change,
    )
    return enqueue_planned(store=store, plan=plan)

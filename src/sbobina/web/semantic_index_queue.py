import logging

from sbobina.ollama_embed import ModelStatus
from sbobina.web.embedding_backfill import (
    BackfillEnqueueError,
    BackfillResult,
    enqueue_planned,
    plan_backfill,
)
from sbobina.web.errors import ServiceUnavailableError
from sbobina.web.job_models import WorkItem
from sbobina.web.supervisor import Supervisor
from sbobina.web.vector_store import VectorStore

logger = logging.getLogger(__name__)


def _publish_items(supervisor: Supervisor, items: tuple[WorkItem, ...]) -> None:
    supervisor._queue.extend(items)
    supervisor._condition.notify()


def submit_backfill(
    *,
    supervisor: Supervisor,
    vectors: VectorStore,
    status: ModelStatus,
    confirm_model_change: bool,
) -> BackfillResult:
    # The scan reads every course's text: it runs outside the queue lock so
    # submissions and cancellations are not held up by it.
    try:
        plan = plan_backfill(
            store=supervisor._store,
            vectors=vectors,
            status=status,
            confirm_model_change=confirm_model_change,
        )
    except Exception as error:
        logger.exception("Backfill scan failed")
        raise ServiceUnavailableError(
            message="Lettura dei corsi non riuscita: nessun corso accodato",
            code="BACKFILL_FAILED",
        ) from error
    with supervisor._condition:
        try:
            result = enqueue_planned(store=supervisor._store, plan=plan)
        except BackfillEnqueueError as error:
            _publish_items(supervisor=supervisor, items=error.items)
            logger.exception(
                "Backfill enqueue failed; published %s items", len(error.items)
            )
            raise ServiceUnavailableError(
                message="Accodamento interrotto: i corsi già accodati restano in elaborazione",
                code="BACKFILL_FAILED",
            ) from error
        _publish_items(supervisor=supervisor, items=result.items)
        return result

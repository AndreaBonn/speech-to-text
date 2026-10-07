from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from sbobina.generation_models import GenerationRequest, GenerationSources
from sbobina.retrieval import RetrievalScope, RetrievedPassage
from sbobina.web.course_retrieval import (
    WindowedQuery,
    course_scope,
    retrieve_windows_with_report,
    sample_course,
)
from sbobina.web.dense_factory import DenseRuntime
from sbobina.web.search_index import SearchIndex

if TYPE_CHECKING:
    from sbobina.web.generation_runner import GenerationJob


@dataclass(frozen=True, kw_only=True)
class GenerationRetrieval:
    job: "GenerationJob"
    dense: DenseRuntime


def _selected_scope(
    scope: RetrievalScope, sources: GenerationSources
) -> RetrievalScope:
    """Narrow scope to explicit source picks; both empty means all."""
    selected = frozenset(sources.doc_ids) | frozenset(sources.job_ids)
    return replace(scope, selected=selected or None)


def retrieve_generation_passages(
    context: GenerationRetrieval,
    index: SearchIndex,
    request: GenerationRequest,
    budget_words: int,
) -> tuple[list[RetrievedPassage], dict[str, object] | None]:
    job = context.job
    scope = _selected_scope(
        scope=course_scope(store=job.store, key=job.course_key),
        sources=job.record.requested_sources,
    )
    if not request.topic.strip():
        return sample_course(
            store=job.store, index=index, scope=scope, budget_words=budget_words
        ), None
    passages, report = retrieve_windows_with_report(
        store=job.store,
        index=index,
        query=WindowedQuery(
            scope=scope, question=request.topic, budget_words=budget_words
        ),
        dense=context.dense.ranker,
    )
    return passages, context.dense.metadata(report=report)

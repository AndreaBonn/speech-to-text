from dataclasses import replace
from pathlib import Path

from test_api_cards import QUOTE, _lecture, _transcript

from sbobina.generation_models import GenerationCitation, GenerationSourceUsed
from sbobina.web.course_retrieval import lecture_revision
from sbobina.web.generation_citations_api import CitationContext
from sbobina.web.job_store import JobStore
from sbobina.web.practice_citations import practice_citation


def citation_context(
    store: JobStore,
    job_id: str,
    revision: str,
) -> tuple[CitationContext, GenerationCitation]:
    context = CitationContext(
        courses_dir=store.courses_dir,
        store=store,
        course_id="unused",
        key="diritto",
        sources=(
            GenerationSourceUsed(
                doc_id=None, sha256=None, job_id=job_id, revision=revision
            ),
        ),
    )
    citation = GenerationCitation(
        passage_id=f"L{job_id}-S0",
        quote=QUOTE,
        doc_id=None,
        page=None,
        job_id=job_id,
        timestamp=0,
    )
    return context, citation


def test_window_citation_links_to_quoted_segment(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    anchor = _lecture(store=store)
    _transcript(store=store, job_id=anchor.job_id, texts=["Introduction", QUOTE])
    revision = lecture_revision(store=store, job_id=anchor.job_id)
    assert revision is not None
    context, citation = citation_context(
        store=store, job_id=anchor.job_id, revision=revision
    )
    current = practice_citation(citation=citation, context=context)
    assert current["status"] == "ok"
    assert current["href"] == f"/lettore/{anchor.job_id}?t=1.0&variant=original"
    _transcript(
        store=store, job_id=anchor.job_id, texts=["Introduction", "More", QUOTE]
    )
    moved = practice_citation(citation=citation, context=context)
    assert moved["status"] == "moved"
    assert moved["href"] == f"/lettore/{anchor.job_id}?t=2.0&variant=original"


def test_legacy_citation_does_not_claim_known_revision(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    anchor = _lecture(store=store)
    context = CitationContext(
        courses_dir=store.courses_dir,
        store=store,
        course_id="unused",
        key="diritto",
        sources=(
            GenerationSourceUsed(
                doc_id=None, sha256=None, job_id=anchor.job_id, revision=anchor.revision
            ),
        ),
    )
    citation = GenerationCitation(
        passage_id=f"L{anchor.job_id}-S0",
        quote=QUOTE,
        doc_id=None,
        page=None,
        job_id=anchor.job_id,
        timestamp=0,
    )
    assert practice_citation(citation=citation, context=context)["status"] == "ok"
    legacy = practice_citation(citation=citation, context=replace(context, sources=()))
    assert legacy["status"] == "unavailable"
    assert legacy["href"] == f"/lettore/{anchor.job_id}?t=0.0&variant=original"

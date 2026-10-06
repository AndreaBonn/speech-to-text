from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from test_api_cards import QUOTE, _lecture, _transcript

from sbobina.card_models import LectureAnchor
from sbobina.generation_models import GenerationCitation, GenerationSourceUsed
from sbobina.web.course_retrieval import lecture_revision
from sbobina.web.generation_citations_api import CitationContext
from sbobina.web.job_store import JobStore
from sbobina.web.practice_citations import (
    citation_anchor,
    fallback_href,
    lecture_anchor,
    practice_citation,
)


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


JOB = str(uuid4())


def _lecture_citation(job_id: str, passage_id: str) -> GenerationCitation:
    return GenerationCitation(
        passage_id=passage_id,
        quote=QUOTE,
        doc_id=None,
        page=None,
        job_id=job_id,
        timestamp=12.5,
    )


def test_citation_anchor_skips_sources_of_other_lectures(tmp_path: Path) -> None:
    context = CitationContext(
        courses_dir=tmp_path,
        store=JobStore(data_dir=tmp_path),
        course_id="unused",
        key="diritto",
        sources=(
            GenerationSourceUsed(
                doc_id=None, sha256=None, job_id=str(uuid4()), revision="r-other"
            ),
            GenerationSourceUsed(doc_id=None, sha256=None, job_id=JOB, revision="r1"),
        ),
    )

    anchor = citation_anchor(
        citation=_lecture_citation(job_id=JOB, passage_id=f"L{JOB}-S4"),
        context=context,
    )

    assert anchor == LectureAnchor(
        job_id=JOB, revision="r1", segment_index=4, quote=QUOTE
    )


@pytest.mark.parametrize(
    "passage_id", ["manuale:p214:c0", "7", f"L{uuid4()}-S3", f"L{JOB}-Sx", f"L{JOB}-S"]
)
def test_lecture_anchor_passage_id_not_of_this_lecture_returns_none(
    passage_id: str,
) -> None:
    assert lecture_anchor(
        citation=_lecture_citation(job_id=JOB, passage_id=f"L{JOB}-S2"), revision="r"
    )
    citation = _lecture_citation(job_id=JOB, passage_id=passage_id)

    assert lecture_anchor(citation=citation, revision="r") is None


def test_fallback_href_lecture_links_to_reader_at_timestamp() -> None:
    citation = _lecture_citation(job_id=JOB, passage_id=f"L{JOB}-S0")

    assert fallback_href(citation=citation, key="diritto") == f"/lettore/{JOB}?t=12.5"


def test_fallback_href_document_quotes_the_course_key() -> None:
    citation = GenerationCitation(
        passage_id="manuale:p3:c0",
        quote=QUOTE,
        doc_id="doc",
        page=3,
        job_id=None,
        timestamp=None,
    )

    assert (
        fallback_href(citation=citation, key="storia/arte")
        == "/corsi/storia%2Farte/documenti/doc?p=3"
    )

import pytest

from sbobina.generation_models import (
    GenerationCitation,
)


def test_generation_citation_rejects_both_doc_and_job_id() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        GenerationCitation(
            passage_id="p1",
            quote="q",
            doc_id="d1",
            page=1,
            job_id="j1",
            timestamp=1.0,
        )


def test_generation_citation_rejects_neither_doc_nor_job_id() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        GenerationCitation(
            passage_id="p1",
            quote="q",
            doc_id=None,
            page=None,
            job_id=None,
            timestamp=None,
        )


def test_generation_citation_rejects_page_without_doc_id() -> None:
    with pytest.raises(ValueError, match="page is set only"):
        GenerationCitation(
            passage_id="p1",
            quote="q",
            doc_id=None,
            page=1,
            job_id="j1",
            timestamp=1.0,
        )


def test_generation_citation_rejects_timestamp_without_job_id() -> None:
    with pytest.raises(ValueError, match="timestamp is set only"):
        GenerationCitation(
            passage_id="p1",
            quote="q",
            doc_id="d1",
            page=1,
            job_id=None,
            timestamp=1.0,
        )


def test_generation_citation_accepts_document_location() -> None:
    citation = GenerationCitation(
        passage_id="manuale:p214:c0",
        quote="q",
        doc_id="manuale",
        page=214,
        job_id=None,
        timestamp=None,
    )
    assert citation.doc_id == "manuale"
    assert citation.page == 214


def test_generation_citation_accepts_lecture_location() -> None:
    citation = GenerationCitation(
        passage_id="Ljob-1-S3",
        quote="q",
        doc_id=None,
        page=None,
        job_id="job-1",
        timestamp=42.5,
    )
    assert citation.job_id == "job-1"
    assert citation.timestamp == 42.5

"""A3: a citation flags when its source changed since the generation ran."""

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from generation_api_fixtures import (
    COURSES_URL,
    _make_record,
    _register_course,
    _store,
    _write_document,
    _write_lecture,
    client,
)

from sbobina.document_models import CourseDocument, DocumentKind, DocumentStatus
from sbobina.generation_models import (
    GenerationCitation,
    GenerationFormat,
    GenerationQuestion,
    GenerationSourceUsed,
    GenerationStatus,
)
from sbobina.web.document_store import write_document
from sbobina.web.generation_citations_api import CitationContext, resolve_citation
from sbobina.web.job_store import JobStore

__all__ = ["client"]

ORIGINAL_SHA256 = "a" * 64
CHANGED_SHA256 = "c" * 64


def _doc_citation(quote: str = "qualunque") -> GenerationQuestion:
    return GenerationQuestion(
        question="Domanda",
        options=(),
        correct_index=None,
        solution="risposta",
        citations=(
            GenerationCitation(
                passage_id="D1",
                quote=quote,
                doc_id="doc-1",
                page=1,
                job_id=None,
                timestamp=None,
            ),
        ),
    )


def _replace_document(tmp_path: Path, course_id: str, sha256: str) -> None:
    write_document(
        courses_dir=_store(tmp_path).courses_dir,
        document=CourseDocument(
            id="doc-1",
            course_id=course_id,
            filename="Manuale.pdf",
            kind=DocumentKind.PDF,
            size=20,
            sha256=sha256,
            status=DocumentStatus.READY,
            error=None,
            pages=1,
            created_at=datetime.now(UTC),
        ),
    )


def test_document_citation_unchanged_source_is_not_flagged(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    _write_document(
        tmp_path=tmp_path, course_id=course_id, doc_id="doc-1", filename="Manuale.pdf"
    )
    record = _make_record(
        tmp_path=tmp_path,
        course_id=course_id,
        format_=GenerationFormat.OPEN,
        status=GenerationStatus.DONE,
        questions=(_doc_citation(),),
        sources=(
            GenerationSourceUsed(
                doc_id="doc-1", sha256=ORIGINAL_SHA256, job_id=None, revision=None
            ),
        ),
    )

    response = client.get(f"{COURSES_URL}/fisica/generations/{record.id}")
    citation = response.json()["data"]["questions"][0]["citations"][0]

    assert citation["changed"] is False


def test_document_citation_changed_after_the_document_was_replaced(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    _write_document(
        tmp_path=tmp_path, course_id=course_id, doc_id="doc-1", filename="Manuale.pdf"
    )
    record = _make_record(
        tmp_path=tmp_path,
        course_id=course_id,
        format_=GenerationFormat.OPEN,
        status=GenerationStatus.DONE,
        questions=(_doc_citation(),),
        sources=(
            GenerationSourceUsed(
                doc_id="doc-1", sha256=ORIGINAL_SHA256, job_id=None, revision=None
            ),
        ),
    )
    # The document was re-uploaded after the generation ran: new content.
    _replace_document(tmp_path=tmp_path, course_id=course_id, sha256=CHANGED_SHA256)

    response = client.get(f"{COURSES_URL}/fisica/generations/{record.id}")
    citation = response.json()["data"]["questions"][0]["citations"][0]

    assert citation["changed"] is True


def test_document_citation_without_registered_sources_is_not_flagged(
    client: TestClient, tmp_path: Path
) -> None:
    # A record saved before this feature has no `sources` at all (T034
    # default): there is nothing to compare against, so never flag.
    course_id = _register_course(tmp_path=tmp_path)
    _write_document(
        tmp_path=tmp_path, course_id=course_id, doc_id="doc-1", filename="Manuale.pdf"
    )
    record = _make_record(
        tmp_path=tmp_path,
        course_id=course_id,
        format_=GenerationFormat.OPEN,
        status=GenerationStatus.DONE,
        questions=(_doc_citation(),),
    )
    _replace_document(tmp_path=tmp_path, course_id=course_id, sha256=CHANGED_SHA256)

    response = client.get(f"{COURSES_URL}/fisica/generations/{record.id}")
    citation = response.json()["data"]["questions"][0]["citations"][0]

    assert citation["changed"] is False


def test_chat_citation_resolution_never_flags_a_change(tmp_path: Path) -> None:
    # Chat builds its CitationContext with no `sources` (api_chat.py): same
    # default as an old record, so the chat path never reports "changed".
    store = JobStore(data_dir=tmp_path)
    course_id = _register_course(tmp_path=tmp_path)
    _write_document(
        tmp_path=tmp_path, course_id=course_id, doc_id="doc-1", filename="Manuale.pdf"
    )
    context = CitationContext(
        courses_dir=store.courses_dir, store=store, course_id=course_id, key="fisica"
    )
    citation = GenerationCitation(
        passage_id="D1",
        quote="qualunque",
        doc_id="doc-1",
        page=1,
        job_id=None,
        timestamp=None,
    )

    result = resolve_citation(citation=citation, context=context)

    assert result["changed"] is False


def test_lecture_citation_changed_after_the_transcript_was_edited(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    _write_lecture(tmp_path=tmp_path, job_id="lezione-1")
    question = GenerationQuestion(
        question="Domanda",
        options=(),
        correct_index=None,
        solution="risposta",
        citations=(
            GenerationCitation(
                passage_id="L1",
                quote="dorme sul tappeto",
                doc_id=None,
                page=None,
                job_id="lezione-1",
                timestamp=0.0,
            ),
        ),
    )
    record = _make_record(
        tmp_path=tmp_path,
        course_id=course_id,
        format_=GenerationFormat.OPEN,
        status=GenerationStatus.DONE,
        questions=(question,),
        sources=(
            GenerationSourceUsed(
                doc_id=None, sha256=None, job_id="lezione-1", revision="stale-revision"
            ),
        ),
    )

    response = client.get(f"{COURSES_URL}/fisica/generations/{record.id}")
    citation = response.json()["data"]["questions"][0]["citations"][0]

    assert citation["changed"] is True

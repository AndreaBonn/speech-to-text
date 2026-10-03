from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from generation_api_fixtures import (
    COURSES_URL,
    _make_record,
    _register_course,
    _store,
    _write_document,
    _write_lecture,
    _write_long_lecture,
    client,
)

from sbobina.document_models import DocumentStatus
from sbobina.extracted_text import ExtractedText, Page
from sbobina.generation_models import (
    GenerationCitation,
    GenerationFormat,
    GenerationQuestion,
    GenerationSourceUsed,
    GenerationStatus,
)
from sbobina.web.document_store import document_dir, write_text

__all__ = ["client"]


def test_get_generation_resolves_document_citation(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    _write_document(
        tmp_path=tmp_path, course_id=course_id, doc_id="doc-1", filename="Manuale.pdf"
    )
    question = GenerationQuestion(
        question="Che cos'e' la forza?",
        options=(),
        correct_index=None,
        solution="massa per accelerazione",
        citations=(
            GenerationCitation(
                passage_id="D1",
                quote="la forza e massa per accelerazione",
                doc_id="doc-1",
                page=12,
                job_id=None,
                timestamp=None,
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
                doc_id="doc-1", sha256="a" * 64, job_id=None, revision=None
            ),
        ),
    )

    response = client.get(f"{COURSES_URL}/fisica/generations/{record.id}")
    citation = response.json()["data"]["questions"][0]["citations"][0]

    assert response.status_code == 200
    assert citation["source"] == "Manuale.pdf"
    assert citation["href"] == "/corsi/fisica/documenti/doc-1?p=12"
    # No text.json written: nothing says the page came from OCR.
    assert citation["ocr"] is False


def test_get_generation_document_citation_removed_source(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    question = GenerationQuestion(
        question="Domanda",
        options=(),
        correct_index=None,
        solution="risposta",
        citations=(
            GenerationCitation(
                passage_id="D1",
                quote="testo citato ma non piu disponibile",
                doc_id="doc-mancante",
                page=3,
                job_id=None,
                timestamp=None,
            ),
        ),
    )
    record = _make_record(
        tmp_path=tmp_path,
        course_id=course_id,
        format_=GenerationFormat.OPEN,
        status=GenerationStatus.DONE,
        questions=(question,),
    )

    response = client.get(f"{COURSES_URL}/fisica/generations/{record.id}")
    citation = response.json()["data"]["questions"][0]["citations"][0]

    assert citation["source"] == "fonte rimossa"
    assert citation["href"] is None


def test_get_generation_resolves_lecture_citation_exact_timestamp(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    _write_lecture(tmp_path=tmp_path, job_id="lezione-1")
    question = GenerationQuestion(
        question="Di che colore e' il gatto?",
        options=(),
        correct_index=None,
        solution="nero",
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
    )

    response = client.get(f"{COURSES_URL}/fisica/generations/{record.id}")
    citation = response.json()["data"]["questions"][0]["citations"][0]

    # The anchor is the segment start (0.0); the cited words start later, at
    # the "dorme" word (3.0s): the resolved timestamp must be the exact one.
    assert citation["timestamp"] == 3.0
    assert citation["href"] == "/lettore/lezione-1?t=3.0&variant=original"


def test_get_generation_lecture_citation_falls_back_to_anchor(
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
                quote="frase che non esiste piu nella trascrizione",
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
    )

    response = client.get(f"{COURSES_URL}/fisica/generations/{record.id}")
    citation = response.json()["data"]["questions"][0]["citations"][0]

    assert citation["timestamp"] == 0.0


def test_get_generation_lecture_citation_removed_source(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    question = GenerationQuestion(
        question="Domanda",
        options=(),
        correct_index=None,
        solution="risposta",
        citations=(
            GenerationCitation(
                passage_id="L1",
                quote="testo di una lezione poi cancellata",
                doc_id=None,
                page=None,
                job_id="lezione-cancellata",
                timestamp=12.0,
            ),
        ),
    )
    record = _make_record(
        tmp_path=tmp_path,
        course_id=course_id,
        format_=GenerationFormat.OPEN,
        status=GenerationStatus.DONE,
        questions=(question,),
    )

    response = client.get(f"{COURSES_URL}/fisica/generations/{record.id}")
    citation = response.json()["data"]["questions"][0]["citations"][0]

    assert citation["source"] == "fonte rimossa"
    assert citation["href"] is None


@pytest.mark.parametrize(
    ("quote", "expected"),
    [("parola41 parola42 parola50", 41.0), ("parola10 parola11 parola12", 10.0)],
)
def test_get_generation_lecture_citation_found_anywhere_in_the_window(
    client: TestClient, tmp_path: Path, quote: str, expected: float
) -> None:
    # Windows start at the anchor (course sampling) or are centred on it
    # (topic search): the quote can sit several segments after or before it.
    course_id = _register_course(tmp_path=tmp_path)
    _write_long_lecture(tmp_path=tmp_path, job_id="lezione-1")
    question = GenerationQuestion(
        question="Domanda",
        options=(),
        correct_index=None,
        solution="risposta",
        citations=(
            GenerationCitation(
                passage_id="Llezione-1-S2",
                quote=quote,
                doc_id=None,
                page=None,
                job_id="lezione-1",
                timestamp=20.0,
            ),
        ),
    )
    record = _make_record(
        tmp_path=tmp_path,
        course_id=course_id,
        format_=GenerationFormat.OPEN,
        status=GenerationStatus.DONE,
        questions=(question,),
    )

    response = client.get(f"{COURSES_URL}/fisica/generations/{record.id}")
    citation = response.json()["data"]["questions"][0]["citations"][0]

    assert citation["timestamp"] == expected


def test_document_citation_says_when_the_page_came_from_ocr(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    _write_document(
        tmp_path=tmp_path, course_id=course_id, doc_id="doc-1", filename="Scan.pdf"
    )
    doc_dir = document_dir(
        courses_dir=_store(tmp_path).courses_dir, course_id=course_id, doc_id="doc-1"
    )
    write_text(
        doc_dir=doc_dir,
        extracted=ExtractedText(
            pages=(Page(text="la forza", no_text=False, ocr=True),),
            status=DocumentStatus.READY,
        ),
    )
    question = GenerationQuestion(
        question="Che cos'e' la forza?",
        options=(),
        correct_index=None,
        solution="massa per accelerazione",
        citations=(
            GenerationCitation(
                passage_id="D1",
                quote="la forza e massa",
                doc_id="doc-1",
                page=1,
                job_id=None,
                timestamp=None,
            ),
        ),
    )
    record = _make_record(
        tmp_path=tmp_path,
        course_id=course_id,
        format_=GenerationFormat.OPEN,
        status=GenerationStatus.DONE,
        questions=(question,),
    )

    response = client.get(f"{COURSES_URL}/fisica/generations/{record.id}")
    citation = response.json()["data"]["questions"][0]["citations"][0]

    assert citation["ocr"] is True

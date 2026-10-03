from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from generation_api_fixtures import (
    COURSES_URL,
    _make_record,
    _register_course,
    _write_lecture,
    _write_long_lecture,
    client,
)

from sbobina.generation_models import (
    GenerationCitation,
    GenerationFormat,
    GenerationQuestion,
    GenerationStatus,
)

__all__ = ["client"]


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

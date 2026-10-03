from io import BytesIO
from pathlib import Path

from docx import Document
from fastapi.testclient import TestClient
from generation_api_fixtures import (
    COURSES_URL,
    _make_record,
    _mc_question,
    _register_course,
    client,
)

from sbobina.generation_models import (
    GenerationFormat,
    GenerationStatus,
    SummarySection,
    SummarySentence,
)

__all__ = ["client"]


def test_download_compito_md_never_contains_solution_text(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    record = _make_record(
        tmp_path=tmp_path,
        course_id=course_id,
        status=GenerationStatus.DONE,
        questions=(_mc_question(correct="la soluzione segreta"),),
    )

    response = client.get(
        f"{COURSES_URL}/fisica/generations/{record.id}/files/compito.md"
    )

    assert response.status_code == 200
    assert "soluzione segreta" not in response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    assert 'filename="compito.md"' in response.headers["content-disposition"]


def test_download_soluzioni_md_contains_solution(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    record = _make_record(
        tmp_path=tmp_path,
        course_id=course_id,
        status=GenerationStatus.DONE,
        questions=(_mc_question(correct="la soluzione segreta"),),
    )

    response = client.get(
        f"{COURSES_URL}/fisica/generations/{record.id}/files/soluzioni.md"
    )

    assert response.status_code == 200
    assert "la soluzione segreta" in response.text


def test_download_generation_file_wrong_format_is_not_found(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    record = _make_record(
        tmp_path=tmp_path,
        course_id=course_id,
        status=GenerationStatus.DONE,
        questions=(_mc_question(correct="x"),),
    )

    response = client.get(
        f"{COURSES_URL}/fisica/generations/{record.id}/files/riassunto.md"
    )

    assert response.status_code == 404


def test_download_generation_file_unknown_name_is_not_found(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    record = _make_record(
        tmp_path=tmp_path, course_id=course_id, status=GenerationStatus.DONE
    )

    response = client.get(
        f"{COURSES_URL}/fisica/generations/{record.id}/files/segreto.txt"
    )

    assert response.status_code == 404


def test_download_generation_file_not_done_is_not_found(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    record = _make_record(tmp_path=tmp_path, course_id=course_id)

    response = client.get(
        f"{COURSES_URL}/fisica/generations/{record.id}/files/compito.md"
    )

    assert response.status_code == 404


def test_download_riassunto_docx(client: TestClient, tmp_path: Path) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    section = SummarySection(
        title="Introduzione",
        sentences=(
            SummarySentence(text="La forza e' massa per accelerazione.", citations=()),
        ),
    )
    record = _make_record(
        tmp_path=tmp_path,
        course_id=course_id,
        format_=GenerationFormat.SUMMARY,
        status=GenerationStatus.DONE,
        sections=(section,),
    )

    response = client.get(
        f"{COURSES_URL}/fisica/generations/{record.id}/files/riassunto.docx"
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def test_download_compito_docx_never_contains_solution_text(
    client: TestClient, tmp_path: Path
) -> None:
    course_id = _register_course(tmp_path=tmp_path)
    record = _make_record(
        tmp_path=tmp_path,
        course_id=course_id,
        status=GenerationStatus.DONE,
        questions=(_mc_question(correct="la soluzione segreta"),),
    )
    base = f"{COURSES_URL}/fisica/generations/{record.id}/files"

    exam = client.get(f"{base}/compito.docx")
    solutions = client.get(f"{base}/soluzioni.docx")

    def text(data: bytes) -> str:
        return "\n".join(p.text for p in Document(BytesIO(data)).paragraphs)

    assert exam.status_code == 200
    assert "soluzione segreta" not in text(exam.content)
    assert "soluzione segreta" in text(solutions.content)

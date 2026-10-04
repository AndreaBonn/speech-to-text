import logging
import os
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from test_practice_models import make_attempt

from sbobina.generation_models import (
    GenerationCitation,
    GenerationFormat,
    GenerationRecord,
    GenerationRequest,
    GenerationStatus,
)
from sbobina.practice_models import PracticeStatus
from sbobina.web.errors import NotFoundError
from sbobina.web.generation_store import (
    create_generation,
    generation_path,
    save_generation,
)
from sbobina.web.practice_store import (
    create_attempt,
    list_attempts,
    load_attempt,
    practice_dir,
    practice_path,
    save_attempt,
)


def make_generation(courses_dir: Path, course_id: str) -> GenerationRecord:
    queued = create_generation(
        courses_dir=courses_dir,
        course_id=course_id,
        request=GenerationRequest(format=GenerationFormat.MULTIPLE_CHOICE, count=2),
    )
    citation = GenerationCitation(
        passage_id="P1",
        quote="Original source",
        doc_id=str(uuid4()),
        page=1,
        job_id=None,
        timestamp=None,
    )
    questions = tuple(
        replace(question, citations=(citation,))
        for question in make_attempt().questions
    )
    record = replace(queued, status=GenerationStatus.DONE, questions=questions)
    save_generation(courses_dir=courses_dir, course_id=course_id, record=record)
    return record


def test_save_attempt_creates_snapshot_file(tmp_path: Path) -> None:
    attempt = make_attempt()
    save_attempt(courses_dir=tmp_path, course_id=attempt.course_id, attempt=attempt)
    path = practice_path(
        courses_dir=tmp_path, course_id=attempt.course_id, attempt_id=attempt.id
    )
    assert path.is_file()
    assert path == tmp_path / attempt.course_id / "practice" / f"{attempt.id}.json"
    assert (
        load_attempt(
            courses_dir=tmp_path, course_id=attempt.course_id, attempt_id=attempt.id
        )
        == attempt
    )


def test_create_attempt_deleted_generation_preserves_snapshot(tmp_path: Path) -> None:
    course_id = str(uuid4())
    generation = make_generation(courses_dir=tmp_path, course_id=course_id)
    attempt = create_attempt(
        courses_dir=tmp_path, course_id=course_id, generation=generation
    )
    assert attempt.questions == generation.questions
    assert attempt.status == PracticeStatus.IN_PROGRESS
    assert attempt.answers == ()
    generation_path(
        courses_dir=tmp_path, course_id=course_id, gen_id=generation.id
    ).unlink()
    assert (
        load_attempt(courses_dir=tmp_path, course_id=course_id, attempt_id=attempt.id)
        == attempt
    )


def test_save_attempt_interrupted_replace_preserves_previous_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = make_attempt()
    save_attempt(courses_dir=tmp_path, course_id=attempt.course_id, attempt=attempt)
    path = practice_path(
        courses_dir=tmp_path, course_id=attempt.course_id, attempt_id=attempt.id
    )
    original = path.read_bytes()
    fail_replacing(target=path, monkeypatch=monkeypatch)
    with pytest.raises(OSError, match="disk full"):
        save_attempt(
            courses_dir=tmp_path,
            course_id=attempt.course_id,
            attempt=replace(attempt, status=PracticeStatus.SUBMITTED),
        )
    assert path.read_bytes() == original
    assert list(path.parent.iterdir()) == [path]
    monkeypatch.undo()
    changed = replace(attempt, status=PracticeStatus.SUBMITTED)
    save_attempt(courses_dir=tmp_path, course_id=attempt.course_id, attempt=changed)
    assert (
        load_attempt(
            courses_dir=tmp_path, course_id=attempt.course_id, attempt_id=attempt.id
        )
        == changed
    )


def fail_replacing(target: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_replace = os.replace

    def fail_replace(src: Path, dst: Path) -> None:
        if dst == target:
            raise OSError("disk full")
        real_replace(src, dst)

    monkeypatch.setattr("sbobina.study_files.os.replace", fail_replace)


def test_list_attempts_returns_all_by_descending_mtime(tmp_path: Path) -> None:
    first = make_attempt()
    second = replace(first, id=str(uuid4()))
    assert list_attempts(courses_dir=tmp_path, course_id=first.course_id).attempts == ()
    for timestamp, attempt in enumerate((first, second), start=1):
        save_attempt(courses_dir=tmp_path, course_id=attempt.course_id, attempt=attempt)
        path = practice_path(
            courses_dir=tmp_path, course_id=attempt.course_id, attempt_id=attempt.id
        )
        os.utime(path=path, times=(timestamp, timestamp))
    scan = list_attempts(courses_dir=tmp_path, course_id=first.course_id)
    assert scan.attempts == (second, first)
    assert scan.unavailable_ids == ()


def test_list_attempts_skips_unreadable_file_and_reports_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    good = make_attempt()
    save_attempt(courses_dir=tmp_path, course_id=good.course_id, attempt=good)
    bad_id = str(uuid4())
    practice_path(
        courses_dir=tmp_path, course_id=good.course_id, attempt_id=bad_id
    ).write_text("{", encoding="utf-8")

    with caplog.at_level(level=logging.ERROR):
        scan = list_attempts(courses_dir=tmp_path, course_id=good.course_id)

    assert scan.attempts == (good,)
    assert scan.unavailable_ids == (bad_id,)
    assert bad_id in caplog.text


@pytest.mark.parametrize("attempt_id", (str(uuid4()), "../escape", "invalid"))
def test_load_attempt_missing_or_invalid_id_not_found(
    tmp_path: Path, attempt_id: str
) -> None:
    with pytest.raises(NotFoundError):
        load_attempt(
            courses_dir=tmp_path, course_id=str(uuid4()), attempt_id=attempt_id
        )


def test_save_attempt_wrong_course_rejected(tmp_path: Path) -> None:
    attempt = make_attempt()
    with pytest.raises(ValueError, match="course_id"):
        save_attempt(courses_dir=tmp_path, course_id=str(uuid4()), attempt=attempt)


@pytest.mark.parametrize(
    "status",
    (
        GenerationStatus.QUEUED,
        GenerationStatus.RUNNING,
        GenerationStatus.INTERRUPTED,
        GenerationStatus.FAILED,
    ),
)
def test_create_attempt_unready_generation_rejected(
    tmp_path: Path, status: GenerationStatus
) -> None:
    course_id = str(uuid4())
    generation = make_generation(courses_dir=tmp_path, course_id=course_id)
    unready = replace(
        generation,
        questions=(),
        status=status,
        error="Failure" if status == GenerationStatus.FAILED else None,
    )
    with pytest.raises(ValueError, match="done"):
        create_attempt(courses_dir=tmp_path, course_id=course_id, generation=unready)


def test_create_attempt_summary_rejected(tmp_path: Path) -> None:
    course_id = str(uuid4())
    generation = make_generation(courses_dir=tmp_path, course_id=course_id)
    summary = replace(generation, format=GenerationFormat.SUMMARY, questions=())
    with pytest.raises(ValueError, match="summary"):
        create_attempt(courses_dir=tmp_path, course_id=course_id, generation=summary)


def test_practice_dir_invalid_course_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="UUID4"):
        practice_dir(courses_dir=tmp_path, course_id="../escape")

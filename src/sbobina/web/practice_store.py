"""Atomic, process-locked storage of self-contained practice attempts."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sbobina.generation_models import (
    GenerationFormat,
    GenerationRecord,
    GenerationStatus,
)
from sbobina.practice_models import (
    PracticeAttempt,
    PracticeStatus,
    dump_practice_attempt,
    load_practice_attempt,
    require_uuid4,
)
from sbobina.study_files import atomic_write_pair
from sbobina.web.errors import NotFoundError
from sbobina.web.path_locks import lock_for

PRACTICE_DIRNAME = "practice"


def practice_dir(courses_dir: Path, course_id: str) -> Path:
    require_uuid4(value=course_id, field="course_id")
    return courses_dir / course_id / PRACTICE_DIRNAME


def practice_path(courses_dir: Path, course_id: str, attempt_id: str) -> Path:
    require_uuid4(value=attempt_id, field="attempt_id")
    return (
        practice_dir(courses_dir=courses_dir, course_id=course_id)
        / f"{attempt_id}.json"
    )


def create_attempt(
    courses_dir: Path,
    course_id: str,
    generation: GenerationRecord,
) -> PracticeAttempt:
    """Persist a fresh snapshot; frozen questions retain their original provenance."""
    if generation.status != GenerationStatus.DONE:
        raise ValueError("generation must be done")
    if generation.format == GenerationFormat.SUMMARY:
        raise ValueError("summary cannot be practiced")
    now = datetime.now(tz=UTC)
    attempt = PracticeAttempt(
        id=str(uuid4()),
        course_id=course_id,
        generation_id=generation.id,
        format=generation.format,
        status=PracticeStatus.IN_PROGRESS,
        created_at=now,
        updated_at=now,
        questions=generation.questions,
        answers=(),
    )
    save_attempt(courses_dir=courses_dir, course_id=course_id, attempt=attempt)
    return attempt


def save_attempt(courses_dir: Path, course_id: str, attempt: PracticeAttempt) -> None:
    if attempt.course_id != course_id:
        raise ValueError("course_id must match the attempt")
    path = practice_path(
        courses_dir=courses_dir, course_id=course_id, attempt_id=attempt.id
    )
    with lock_for(path=path):
        atomic_write_pair(contents={path: dump_practice_attempt(attempt=attempt)})


def load_attempt(courses_dir: Path, course_id: str, attempt_id: str) -> PracticeAttempt:
    try:
        path = practice_path(
            courses_dir=courses_dir, course_id=course_id, attempt_id=attempt_id
        )
    except ValueError as error:
        raise NotFoundError(entity="Tentativo", id=attempt_id) from error
    try:
        return load_practice_attempt(content=path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise NotFoundError(entity="Tentativo", id=attempt_id) from error


def list_attempts(courses_dir: Path, course_id: str) -> list[PracticeAttempt]:
    directory = practice_dir(courses_dir=courses_dir, course_id=course_id)
    paths = sorted(
        directory.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True
    )
    return [
        load_attempt(courses_dir=courses_dir, course_id=course_id, attempt_id=path.stem)
        for path in paths
    ]

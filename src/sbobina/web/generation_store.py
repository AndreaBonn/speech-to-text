"""File I/O for queued/running/done generation records.

Each record lives at courses/<course_id>/generations/<gen_id>.json. There is
no in-memory index: callers that already know the course_id (the WorkItem
does) go straight to the file; recovery and the child's own lookup of "the
generation it was launched for" scan the course's generations directory.
"""

import logging
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

from sbobina.generation_models import (
    GenerationRecord,
    GenerationRequest,
    GenerationStatus,
    dump_generation,
)
from sbobina.generation_models import load_generation as parse_generation
from sbobina.study_files import atomic_write_pair
from sbobina.web.errors import GenerationUnreadableError, NotFoundError

logger = logging.getLogger("sbobina")

GENERATIONS_DIRNAME = "generations"


def generation_dir(courses_dir: Path, course_id: str) -> Path:
    return courses_dir / course_id / GENERATIONS_DIRNAME


def generation_path(courses_dir: Path, course_id: str, gen_id: str) -> Path:
    return (
        generation_dir(courses_dir=courses_dir, course_id=course_id) / f"{gen_id}.json"
    )


def save_generation(
    courses_dir: Path, course_id: str, record: GenerationRecord
) -> None:
    path = generation_path(
        courses_dir=courses_dir, course_id=course_id, gen_id=record.id
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_pair(contents={path: dump_generation(record)})


def load_generation(courses_dir: Path, course_id: str, gen_id: str) -> GenerationRecord:
    path = generation_path(courses_dir=courses_dir, course_id=course_id, gen_id=gen_id)
    try:
        return parse_generation(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise NotFoundError(entity="Generazione", id=gen_id) from error
    except ValueError as error:
        raise GenerationUnreadableError(gen_id=gen_id) from error


def create_generation(
    courses_dir: Path, course_id: str, request: GenerationRequest
) -> GenerationRecord:
    record = GenerationRecord(
        id=str(uuid4()),
        format=request.format,
        status=GenerationStatus.QUEUED,
        requested_count=request.count,
        topic=request.topic,
        model="",
        prompt_version="",
        generated_at="",
        sources=(),
        discarded=(),
        questions=(),
        sections=(),
        error=None,
        requested_sources=request.sources,
    )
    save_generation(courses_dir=courses_dir, course_id=course_id, record=record)
    return record


def iter_generations(courses_dir: Path) -> Iterator[tuple[str, GenerationRecord]]:
    """Every persisted generation across all courses, course_id first.

    A malformed file is skipped with a warning: one corrupt record must not
    stop recovery for every other course (mirrors _claim's leniency).
    """
    for path in courses_dir.glob(f"*/{GENERATIONS_DIRNAME}/*.json"):
        course_id = path.parent.parent.name
        try:
            yield course_id, parse_generation(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            logger.warning("Generazione non leggibile, salto %s: %s", path, error)


def find_running(courses_dir: Path, course_id: str) -> GenerationRecord:
    """The one generation the supervisor just marked RUNNING for this course.

    Only one child process runs at a time across the whole app (see
    test_pipeline_then_study_never_overlap_children's generation sibling), so
    exactly one record is RUNNING when the child starts: this is how it
    learns its own gen_id without it travelling as a CLI argument.
    """
    directory = generation_dir(courses_dir=courses_dir, course_id=course_id)
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else ():
        try:
            record = parse_generation(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            logger.warning("Generazione non leggibile, salto %s: %s", path, error)
            continue
        if record.status == GenerationStatus.RUNNING:
            return record
    raise NotFoundError(entity="Generazione in esecuzione", id=course_id)

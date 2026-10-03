"""File I/O for queued/running/done OCR runs (T051, second half).

Each record lives next to the document it belongs to, at
``courses/<course_id>/documents/<doc_id>/ocr.json``. Mirrors
generation_store.py: no in-memory index, callers that already know
course_id/doc_id (the WorkItem does) go straight to the file; recovery scans
every course's documents.
"""

import json
import logging
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from sbobina.study_files import atomic_write_pair
from sbobina.web.document_store import document_dir

logger = logging.getLogger("sbobina")

OCR_FILENAME = "ocr.json"


class OcrStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class OcrRun:
    status: OcrStatus
    done: int
    total: int
    error: str | None

    def __post_init__(self) -> None:
        # error is reserved for FAILED, mirroring GenerationRecord: an
        # INTERRUPTED run (cancelled, or killed by a server restart) is not
        # a failure and carries no error code.
        if (self.error is not None) != (self.status is OcrStatus.FAILED):
            raise ValueError(f"error is set only when failed, got {self.status}")
        if self.done < 0 or self.total < 0:
            raise ValueError("done/total must not be negative")
        if self.done > self.total:
            raise ValueError(f"done ({self.done}) must not exceed total ({self.total})")


def ocr_path(courses_dir: Path, course_id: str, doc_id: str) -> Path:
    return (
        document_dir(courses_dir=courses_dir, course_id=course_id, doc_id=doc_id)
        / OCR_FILENAME
    )


def _to_json(record: OcrRun) -> str:
    return json.dumps(asdict(record) | {"status": record.status.value})


def _from_json(raw: dict[str, Any]) -> OcrRun:
    return OcrRun(
        status=OcrStatus(raw["status"]),
        done=int(raw["done"]),
        total=int(raw["total"]),
        error=None if raw["error"] is None else str(raw["error"]),
    )


def save_ocr(courses_dir: Path, course_id: str, doc_id: str, record: OcrRun) -> None:
    path = ocr_path(courses_dir=courses_dir, course_id=course_id, doc_id=doc_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_pair(contents={path: _to_json(record=record)})


def load_ocr(courses_dir: Path, course_id: str, doc_id: str) -> OcrRun | None:
    path = ocr_path(courses_dir=courses_dir, course_id=course_id, doc_id=doc_id)
    if not path.is_file():
        return None
    return _from_json(json.loads(path.read_text(encoding="utf-8")))


def create_ocr(courses_dir: Path, course_id: str, doc_id: str) -> OcrRun:
    record = OcrRun(status=OcrStatus.QUEUED, done=0, total=0, error=None)
    save_ocr(courses_dir=courses_dir, course_id=course_id, doc_id=doc_id, record=record)
    return record


def iter_ocr_runs(courses_dir: Path) -> Iterator[tuple[str, str, OcrRun]]:
    """Every persisted OCR run across all courses, as (course_id, doc_id, record).

    A malformed file is skipped with a warning, same leniency as
    generation_store.iter_generations: one corrupt record must not stop
    recovery for every other document.
    """
    for path in courses_dir.glob(f"*/documents/*/{OCR_FILENAME}"):
        course_id = path.parent.parent.parent.name
        doc_id = path.parent.name
        try:
            yield (
                course_id,
                doc_id,
                _from_json(json.loads(path.read_text(encoding="utf-8"))),
            )
        except (OSError, ValueError) as error:
            logger.warning("OCR non leggibile, salto %s: %s", path, error)


__all__ = [
    "OcrRun",
    "OcrStatus",
    "create_ocr",
    "iter_ocr_runs",
    "load_ocr",
    "ocr_path",
    "save_ocr",
]

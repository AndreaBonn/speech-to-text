import json
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path

from sbobina.study_files import atomic_write_pair

EMBEDDING_FILENAME = "embedding.json"


class EmbeddingStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class EmbeddingRun:
    status: EmbeddingStatus
    processed: int
    total: int
    error: str | None

    def __post_init__(self) -> None:
        if (self.error is not None) != (self.status is EmbeddingStatus.FAILED):
            raise ValueError("error must be set exactly when failed")
        if not 0 <= self.processed <= self.total:
            raise ValueError("progress must satisfy 0 <= processed <= total")


def save_embed(course_dir: Path, record: EmbeddingRun) -> None:
    course_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_pair(
        contents={course_dir / EMBEDDING_FILENAME: json.dumps(asdict(record))}
    )


def load_embed(course_dir: Path) -> EmbeddingRun | None:
    path = course_dir / EMBEDDING_FILENAME
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return EmbeddingRun(
        status=EmbeddingStatus(raw["status"]),
        processed=int(raw["processed"]),
        total=int(raw["total"]),
        error=None if raw["error"] is None else str(raw["error"]),
    )


def create_embed(course_dir: Path) -> EmbeddingRun:
    record = EmbeddingRun(
        status=EmbeddingStatus.QUEUED, processed=0, total=0, error=None
    )
    save_embed(course_dir=course_dir, record=record)
    return record


def finish_embed(
    course_dir: Path, status: EmbeddingStatus, error: str | None = None
) -> None:
    record = load_embed(course_dir=course_dir)
    if record is not None and record.status == EmbeddingStatus.RUNNING:
        save_embed(
            course_dir=course_dir, record=replace(record, status=status, error=error)
        )

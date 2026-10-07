import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
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
    last_indexed_at: datetime | None = None

    def __post_init__(self) -> None:
        if (self.error is not None) != (self.status is EmbeddingStatus.FAILED):
            raise ValueError("error must be set exactly when failed")
        if not 0 <= self.processed <= self.total:
            raise ValueError("progress must satisfy 0 <= processed <= total")


def save_embed(course_dir: Path, record: EmbeddingRun) -> None:
    course_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_pair(
        contents={
            course_dir / EMBEDDING_FILENAME: json.dumps(asdict(record), default=str)
        }
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
        last_indexed_at=datetime.fromisoformat(raw["last_indexed_at"])
        if raw.get("last_indexed_at")
        else None,
    )


def create_embed(course_dir: Path) -> EmbeddingRun:
    previous = load_embed(course_dir=course_dir)
    record = EmbeddingRun(
        status=EmbeddingStatus.QUEUED,
        processed=0,
        total=0,
        error=None,
        last_indexed_at=previous.last_indexed_at if previous else None,
    )
    save_embed(course_dir=course_dir, record=record)
    return record


def finish_embed(
    course_dir: Path, status: EmbeddingStatus, error: str | None = None
) -> None:
    record = load_embed(course_dir=course_dir)
    if record is not None and record.status == EmbeddingStatus.RUNNING:
        save_embed(
            course_dir=course_dir,
            record=replace(
                record,
                status=status,
                error=error,
                last_indexed_at=datetime.now(tz=UTC)
                if status is EmbeddingStatus.DONE
                else record.last_indexed_at,
            ),
        )

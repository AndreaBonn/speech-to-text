import json
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

from sbobina.courses import course_key, normalize_course_label
from sbobina.study_files import atomic_write_pair

REGISTRY_LOCK = RLock()


class CourseRequiredError(ValueError):
    code = "COURSE_REQUIRED"


class CourseExistsError(ValueError):
    code = "COURSE_EXISTS"


@dataclass(frozen=True)
class CourseRecord:
    id: str
    key: str
    label: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        # The id names a directory and the key decides which lectures belong
        # here: both must hold for every record, not only the factory's ones.
        UUID(self.id)
        if not self.key or self.key != course_key(label=self.label):
            raise ValueError(f"course key {self.key!r} does not match its label")


def iter_courses(courses_dir: Path) -> Iterator[CourseRecord]:
    """Read registered courses; malformed records propagate to the caller."""
    for path in courses_dir.glob("*/course.json"):
        raw = json.loads(path.read_text(encoding="utf-8"))
        yield CourseRecord(
            id=str(UUID(raw["id"])),
            key=raw["key"],
            label=raw["label"],
            created_at=datetime.fromisoformat(raw["created_at"]),
            updated_at=datetime.fromisoformat(raw["updated_at"]),
        )


def find_by_key(courses_dir: Path, key: str) -> CourseRecord | None:
    """Find a course by its normalized key, without creating storage."""
    return next((item for item in iter_courses(courses_dir) if item.key == key), None)


def _write_course(courses_dir: Path, record: CourseRecord) -> None:
    values = asdict(record) | {
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }
    atomic_write_pair(
        contents={
            courses_dir / record.id / "course.json": json.dumps(
                values, ensure_ascii=False
            )
        }
    )


def _validate_label(key: str, label: str) -> str:
    if not course_key(label=key):
        raise CourseRequiredError("A named course is required")
    normalized = normalize_course_label(raw=label)
    if normalized is None or course_key(label=normalized) != key:
        raise ValueError("The label must match the normalized course key")
    return normalized


def get_or_create(courses_dir: Path, key: str, label: str) -> CourseRecord:
    """Create a stable UUID4 course, idempotently within the server process."""
    normalized = _validate_label(key=key, label=label)
    with REGISTRY_LOCK:
        existing = find_by_key(courses_dir=courses_dir, key=key)
        if existing is not None:
            return existing
        now = datetime.now(tz=UTC)
        record = CourseRecord(
            id=str(uuid4()), key=key, label=normalized, created_at=now, updated_at=now
        )
        _write_course(courses_dir=courses_dir, record=record)
        return record


def rename_key(
    courses_dir: Path, old: str, new: str, update_lectures: Callable[[str, str], None]
) -> CourseRecord:
    """Persist the new label/key before updating lectures through the callback.

    Callback failures propagate; the registry retains the new identity and label.
    The caller verifies lecture-only sources; these receive a new identity.
    The callback receives the old key and normalized new display label.
    """
    key = course_key(label=new)
    label = _validate_label(key=key, label=new)
    if not course_key(label=old):
        raise CourseRequiredError("A named course is required")
    with REGISTRY_LOCK:
        record = find_by_key(courses_dir=courses_dir, key=old)
        destination = find_by_key(courses_dir=courses_dir, key=key)
        if destination is not None and destination != record:
            raise CourseExistsError("The destination course already exists")
        if record is None:
            record = get_or_create(courses_dir=courses_dir, key=key, label=label)
        renamed = replace(record, key=key, label=label, updated_at=datetime.now(tz=UTC))
        _write_course(courses_dir=courses_dir, record=renamed)
        update_lectures(old, label)
        return renamed

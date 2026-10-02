import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

MAX_COURSE_LABEL_LENGTH = 100
UNCATEGORIZED_COURSE_KEY = ""
UNCATEGORIZED_COURSE_LABEL = "Senza corso"


@dataclass(frozen=True)
class CourseLecture:
    course: str | None
    subject: str | None
    created_at: datetime


@dataclass(frozen=True)
class CourseSummary:
    key: str
    label: str
    lecture_count: int
    last_lecture_at: datetime


def _clean_course_label(raw: str | None) -> str | None:
    if raw is None:
        return None
    return " ".join(unicodedata.normalize("NFKC", raw).split()) or None


def normalize_course_label(raw: str | None) -> str | None:
    label = _clean_course_label(raw=raw)
    if label is not None and len(label) > MAX_COURSE_LABEL_LENGTH:
        raise ValueError(
            f"Il corso può contenere al massimo {MAX_COURSE_LABEL_LENGTH} caratteri"
        )
    return label


def course_key(label: str | None) -> str:
    normalized = _clean_course_label(raw=label)
    return normalized.casefold() if normalized else UNCATEGORIZED_COURSE_KEY


def effective_course(course: str | None, subject: str | None) -> str | None:
    # Legacy subjects were limited before NFKC, which can expand their length.
    return normalize_course_label(raw=course) or _clean_course_label(raw=subject)


def group_courses(records: Iterable[CourseLecture]) -> list[CourseSummary]:
    """Group lectures by effective course, newest first without mutating inputs."""
    groups: dict[str, CourseSummary] = {}
    for record in sorted(records, key=lambda item: item.created_at, reverse=True):
        label = effective_course(course=record.course, subject=record.subject)
        key = course_key(label=label)
        previous = groups.get(key)
        groups[key] = CourseSummary(
            key=key,
            label=previous.label if previous else label or UNCATEGORIZED_COURSE_LABEL,
            lecture_count=previous.lecture_count + 1 if previous else 1,
            last_lecture_at=previous.last_lecture_at if previous else record.created_at,
        )
    return list(groups.values())

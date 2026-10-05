"""Loaded package records and import provenance, independent of persistence."""

from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime

from sbobina.card_models import CardEvent
from sbobina.course_registry import CourseRecord
from sbobina.document_models import CourseDocument
from sbobina.generation_models import GenerationRecord
from sbobina.package_models import Manifest


@dataclass(frozen=True, kw_only=True)
class PackageJob:
    id: str
    created_at: datetime
    updated_at: datetime
    source_name: str


@dataclass(frozen=True, kw_only=True)
class PackageContent:
    course_id: str | None = None
    jobs: tuple[PackageJob, ...] = ()
    documents: tuple[CourseDocument, ...] = ()
    generations: tuple[GenerationRecord, ...] = ()
    cards: tuple[CardEvent, ...] = ()


@dataclass(frozen=True, kw_only=True)
class RemapRequest:
    manifest: Manifest
    content: PackageContent
    existing_course_keys: frozenset[str] = frozenset()


@dataclass(frozen=True, kw_only=True)
class IdMaps:
    courses: Mapping[str, str]
    jobs: Mapping[str, str]
    documents: Mapping[str, str]
    generations: Mapping[str, str]
    cards: Mapping[str, str]


@dataclass(frozen=True, kw_only=True)
class ImportedFrom:
    package_id: str
    ids: IdMaps

    def to_dict(self) -> dict[str, str | dict[str, dict[str, str]]]:
        """Project read-only ID maps into JSON-serializable import provenance."""
        return {
            "package_id": self.package_id,
            "ids": {
                field.name: dict(getattr(self.ids, field.name))
                for field in fields(self.ids)
            },
        }


@dataclass(frozen=True, kw_only=True)
class RemappedPackage:
    course: CourseRecord
    content: PackageContent
    imported_from: ImportedFrom

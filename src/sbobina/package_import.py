"""Filesystem-only course import; HTTP and child-process execution live elsewhere."""

import logging
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from pydantic import TypeAdapter

from sbobina.course_registry import REGISTRY_LOCK, CourseRecord, iter_courses
from sbobina.package_import_commit import import_staging
from sbobina.package_import_load import LoadedPackage, load_package
from sbobina.package_import_stage import (
    PROVENANCE_FILENAME,
    StageRequest,
    stage_package,
)
from sbobina.package_models import Manifest
from sbobina.package_remap import remap_package
from sbobina.package_remap_types import ImportedFrom, RemapRequest
from sbobina.package_validate import (
    DEFAULT_LIMITS,
    PackageInvalidError,
    PackageValidationError,
    ValidationLimits,
    validate_package,
)
from sbobina.time_guards import require_aware

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class ImportResult:
    course: CourseRecord
    imported_from: ImportedFrom
    warning: str | None


@dataclass(frozen=True, kw_only=True)
class _Provenance:
    package_id: str
    imported_at: datetime


PROVENANCE_ADAPTER = TypeAdapter(_Provenance)


def _previous_warning(courses_dir: Path, package_id: str) -> str | None:
    dates = []
    for course in iter_courses(courses_dir=courses_dir):
        path = courses_dir / course.id / PROVENANCE_FILENAME
        if path.exists():
            previous = PROVENANCE_ADAPTER.validate_json(path.read_bytes())
            if previous.package_id == package_id:
                dates.append(previous.imported_at)
    return f"già importato il {min(dates).isoformat()}" if dates else None


class PackageStorageError(OSError):
    """The package was valid but the course could not be written to disk."""

    code = "PACKAGE_STORAGE_FAILED"


def _import(
    source: Path, data_dir: Path, now: datetime, limits: ValidationLimits
) -> ImportResult:
    with source.open(mode="rb") as stream:
        validated = validate_package(source=stream, limits=limits)
        with ZipFile(file=stream) as archive:
            loaded = load_package(archive=archive, manifest=validated.manifest)
    with REGISTRY_LOCK:
        return _publish_package(
            loaded=loaded, manifest=validated.manifest, data_dir=data_dir, now=now
        )


def _publish_package(
    loaded: LoadedPackage, manifest: Manifest, data_dir: Path, now: datetime
) -> ImportResult:
    courses_dir = data_dir / "courses"
    keys = frozenset(course.key for course in iter_courses(courses_dir=courses_dir))
    remapped = remap_package(
        request=RemapRequest(
            manifest=manifest,
            content=loaded.content,
            existing_course_keys=keys,
        )
    )
    warning = _previous_warning(
        courses_dir=courses_dir, package_id=remapped.imported_from.package_id
    )
    with import_staging(data_dir=data_dir) as staging:
        stage_package(
            request=StageRequest(
                loaded=loaded, remapped=remapped, staging=staging, now=now
            )
        )
        staging.publish(
            course_id=remapped.course.id,
            job_ids=tuple(job.id for job in remapped.content.jobs),
        )
    return ImportResult(
        course=remapped.course, imported_from=remapped.imported_from, warning=warning
    )


def import_package(
    source: Path,
    data_dir: Path,
    now: datetime,
    limits: ValidationLimits = DEFAULT_LIMITS,
) -> ImportResult:
    """Validate, remap and publish a new course, rolling back any failed import.

    Parameters
    ----------
    source : Path
        Untrusted package archive; only manifest members are decoded.
    data_dir : Path
        Local storage root. New parent directories are removed on rollback.
    now : datetime
        Aware import time persisted in course ``imported_from.json`` alongside
        package_id and ID maps. Job ``import.json`` holds import_id=course.id;
        readers will consume this visibility marker in T092.
    limits : ValidationLimits
        Archive budgets. Reimports create a new course and return a dated warning.
    """
    require_aware(value=now, field="now")
    try:
        return _import(source=source, data_dir=data_dir, now=now, limits=limits)
    except PackageValidationError as error:
        logger.warning("Course package rejected: %s", error)
        raise
    except (ValueError, KeyError, TypeError, BadZipFile, zlib.error) as error:
        logger.warning("Course package content invalid: %s", error)
        raise PackageInvalidError("Invalid package content") from error
    except OSError as error:
        logger.error("Course import failed on disk: %s", error)
        raise PackageStorageError("Could not write the imported course") from error

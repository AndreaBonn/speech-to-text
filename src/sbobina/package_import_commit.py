"""Directory transaction for an import; course publication is the last rename."""

import logging
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass(kw_only=True)
class ImportStaging:
    courses: Path
    jobs: Path
    published: list[Path] = field(default_factory=list)
    committed: bool = False

    def publish(self, course_id: str, job_ids: tuple[str, ...]) -> None:
        sources = tuple(self.jobs / job_id for job_id in job_ids)
        for source in (*sources, self.courses / course_id):
            destination = source.parent.parent / source.name
            if destination.exists():
                raise FileExistsError(destination)
            source.rename(target=destination)
            self.published.append(destination)
        self.committed = True


def _missing_parents(path: Path) -> tuple[Path, ...]:
    return tuple(parent for parent in (path, *path.parents) if not parent.exists())


def _remove(path: Path, level: int) -> None:
    # A cleanup step that fails is logged and skipped: on rollback the import's
    # own error must reach the caller, after a commit the import has succeeded.
    try:
        if path.is_dir() and not path.is_symlink() and any(path.iterdir()):
            shutil.rmtree(path=path)
        elif path.exists():
            path.rmdir()
    except OSError as error:
        logger.log(level, "Course import left %s behind: %s", path, error)


def _rollback(staging: ImportStaging, created: tuple[Path, ...]) -> None:
    for path in (*reversed(staging.published), staging.jobs, staging.courses):
        _remove(path=path, level=logging.ERROR)
    for path in created:
        _remove(path=path, level=logging.ERROR)


@contextmanager
def import_staging(data_dir: Path) -> Iterator[ImportStaging]:
    """Remove staging and owned output on failure, preserving pre-existing trees."""
    courses, jobs = data_dir / "courses", data_dir / "jobs"
    created = tuple(
        dict.fromkeys((*_missing_parents(path=courses), *_missing_parents(path=jobs)))
    )
    created = tuple(sorted(created, key=lambda path: len(path.parts), reverse=True))
    staging = ImportStaging(
        courses=courses / f".import-{uuid4()}", jobs=jobs / f".import-{uuid4()}"
    )
    try:
        staging.courses.mkdir(parents=True)
        staging.jobs.mkdir(parents=True)
        yield staging
    except BaseException:
        _rollback(staging=staging, created=created)
        raise
    for path in (staging.jobs, staging.courses):
        _remove(path=path, level=logging.WARNING)

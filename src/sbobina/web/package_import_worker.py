"""Blocking course import in an isolated child, outside the GPU queue."""

import json
import logging
import shutil
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory

from sbobina.course_registry import iter_courses
from sbobina.package_import_stage import PROVENANCE_FILENAME
from sbobina.web.processes import _reap, _spawn

DEFAULT_COMMAND = (sys.executable, "-m", "sbobina.web.package_import_runner")
# BASIS: inferred; allow archive validation and staging more time than extraction.
DEFAULT_TIMEOUT_S = 300.0
# BASIS: inferred; reuse extraction's 2 GiB budget until import usage is measured.
DEFAULT_MAX_MEMORY_MB = 2048
TERMINATE_TIMEOUT_S = 5.0
# package_import_runner exits with this on MemoryError; -9 is the kernel's kill.
MEMORY_EXIT_CODE = 3
MEMORY_EXIT_CODES = frozenset({MEMORY_EXIT_CODE, -signal.SIGKILL})


class PackageImportStatus(StrEnum):
    IMPORTED = "imported"
    REJECTED = "rejected"
    STORAGE_ERROR = "storage_error"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    TIMEOUT = "timeout"
    BUSY = "busy"
    FAILED = "failed"


@dataclass(frozen=True)
class PackageImportOutcome:
    status: PackageImportStatus
    code: str | None = None
    message: str | None = None
    course_id: str | None = None
    course_label: str | None = None
    warning: str | None = None


@dataclass(frozen=True)
class PackageImportOptions:
    command: tuple[str, ...] = DEFAULT_COMMAND
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_memory_mb: int = DEFAULT_MAX_MEMORY_MB
    terminate_timeout_s: float = TERMINATE_TIMEOUT_S


DEFAULT_OPTIONS = PackageImportOptions()
# One import per process. Enough today: the web server runs a single uvicorn
# process and nothing else imports; a second process would need a file lock.
_IMPORT_LOCK = threading.Lock()
logger = logging.getLogger(__name__)


def _required_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise TypeError(f"Invalid import result field: {key}")
    return value


def _decode_outcome(payload: object) -> PackageImportOutcome:
    if not isinstance(payload, dict):
        raise TypeError("Import result must be an object")
    status = PackageImportStatus(_required_text(payload=payload, key="status"))
    if status is PackageImportStatus.IMPORTED:
        warning = payload["warning"]
        if warning is not None and not isinstance(warning, str):
            raise ValueError("Invalid import warning")
        return PackageImportOutcome(
            status=status,
            course_id=_required_text(payload=payload, key="course_id"),
            course_label=_required_text(payload=payload, key="course_label"),
            warning=warning,
        )
    if status in (PackageImportStatus.REJECTED, PackageImportStatus.STORAGE_ERROR):
        return PackageImportOutcome(
            status=status,
            code=_required_text(payload=payload, key="code"),
            message=_required_text(payload=payload, key="message"),
        )
    raise ValueError("Unsupported child import status")


def _read_outcome(result_path: Path, returncode: int | None) -> PackageImportOutcome:
    """A valid result wins; otherwise the exit code says memory or crash."""
    try:
        payload = json.loads(s=result_path.read_text(encoding="utf-8"))
        return _decode_outcome(payload=payload)
    except (OSError, ValueError, KeyError, TypeError) as error:
        logger.error(
            "Import child left no valid result (exit %s): %s", returncode, error
        )
    if returncode in MEMORY_EXIT_CODES:
        return PackageImportOutcome(
            status=PackageImportStatus.RESOURCE_EXHAUSTED,
            code="PACKAGE_FAILED",
            message="Import child ran out of memory",
        )
    return PackageImportOutcome(
        status=PackageImportStatus.FAILED,
        code="PACKAGE_IMPORT_FAILED",
        message="Import child failed to produce a valid result",
    )


def _course_ids(data_dir: Path) -> frozenset[str]:
    directory = data_dir / "courses"
    if not directory.is_dir():
        return frozenset()
    return frozenset(p.name for p in directory.iterdir() if not p.name.startswith("."))


def _late_publication(
    data_dir: Path, before: frozenset[str]
) -> PackageImportOutcome | None:
    """The course a child killed after its final rename had already published.

    Only an import writes the provenance file and _IMPORT_LOCK admits one
    import at a time, so a new course carrying it is this import's.
    """
    try:
        courses = tuple(iter_courses(courses_dir=data_dir / "courses"))
    except (OSError, ValueError, KeyError) as error:
        logger.error("Could not check for a published import: %s", error)
        return None
    for course in courses:
        provenance = data_dir / "courses" / course.id / PROVENANCE_FILENAME
        if course.id not in before and provenance.is_file():
            return PackageImportOutcome(
                status=PackageImportStatus.IMPORTED,
                course_id=course.id,
                course_label=course.label,
                message="Imported; the child was stopped while reporting",
            )
    return None


def _remove_staging(data_dir: Path) -> None:
    # Safe only because _IMPORT_LOCK admits one import per process: the reaped
    # child can no longer write here and no other import is staging.
    for name in ("courses", "jobs"):
        for path in (data_dir / name).glob(pattern=".import-*"):
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path=path)


def _wait_for_import(
    process: subprocess.Popen[bytes], options: PackageImportOptions
) -> bool:
    try:
        process.wait(timeout=options.timeout_s)
        return True
    except subprocess.TimeoutExpired:
        _reap(process=process, timeout_s=options.terminate_timeout_s, graceful=False)
        return False
    finally:
        if process.stdin is not None:
            process.stdin.close()


def run_package_import(
    source: Path,
    data_dir: Path,
    now: datetime,
    options: PackageImportOptions = DEFAULT_OPTIONS,
) -> PackageImportOutcome:
    """Import synchronously in a child; offload it from the asyncio loop.

    A second import while one runs returns BUSY instead of waiting: the
    timeout cleanup removes every staging directory and must not hit another
    import's.
    """
    if not _IMPORT_LOCK.acquire(blocking=False):
        return PackageImportOutcome(
            status=PackageImportStatus.BUSY,
            code="PACKAGE_IMPORT_BUSY",
            message="Another course import is running",
        )
    try:
        return _run_child(source=source, data_dir=data_dir, now=now, options=options)
    finally:
        _IMPORT_LOCK.release()


def _run_child(
    source: Path, data_dir: Path, now: datetime, options: PackageImportOptions
) -> PackageImportOutcome:
    before = _course_ids(data_dir=data_dir)
    with TemporaryDirectory(prefix="sbobina-import-") as temporary:
        result_path = Path(temporary) / "result.json"
        process = _spawn(
            command=[
                *options.command,
                str(source),
                str(data_dir),
                now.isoformat(),
                str(options.max_memory_mb),
                str(result_path),
            ],
            log_path=Path(temporary) / "import.log",
        )
        if not _wait_for_import(process=process, options=options):
            _remove_staging(data_dir=data_dir)
            return _late_publication(data_dir=data_dir, before=before) or (
                PackageImportOutcome(
                    status=PackageImportStatus.TIMEOUT,
                    code="PACKAGE_IMPORT_TIMEOUT",
                    message="Import child exceeded its time budget",
                )
            )
        return _read_outcome(result_path=result_path, returncode=process.returncode)

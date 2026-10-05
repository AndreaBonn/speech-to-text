"""Child CLI: limit memory before importing and report only known domain outcomes."""

import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sbobina.package_import import PackageStorageError, import_package
from sbobina.package_validate import PackageValidationError, ValidationLimits
from sbobina.web.child_limits import _apply_memory_limit
from sbobina.web.package_import_worker import MEMORY_EXIT_CODE, PackageImportStatus
from sbobina.web.upload_limit import BYTES_PER_MB

logger = logging.getLogger(__name__)
ARGUMENT_COUNT = 6


@dataclass(frozen=True)
class ImportRequest:
    source: Path
    data_dir: Path
    now: datetime
    limits: ValidationLimits


def run_import(request: ImportRequest, max_memory_mb: int, result_path: Path) -> None:
    """Apply the memory budget, import within the request limits, write the result."""
    _apply_memory_limit(max_memory_mb=max_memory_mb)
    payload: dict[str, str | None]
    try:
        imported = import_package(
            source=request.source,
            data_dir=request.data_dir,
            now=request.now,
            limits=request.limits,
        )
        payload = {
            "status": PackageImportStatus.IMPORTED,
            "course_id": imported.course.id,
            "course_label": imported.course.label,
            "warning": imported.warning,
        }
    except PackageValidationError as error:
        payload = {
            "status": PackageImportStatus.REJECTED,
            "code": error.code,
            "message": str(error),
        }
    except PackageStorageError as error:
        payload = {
            "status": PackageImportStatus.STORAGE_ERROR,
            "code": error.code,
            "message": str(error),
        }
    result_path.write_text(data=json.dumps(obj=payload), encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != ARGUMENT_COUNT:
        logger.error(
            "Usage: package_import_runner <source> <data_dir> <now> "
            "<max_memory_mb> <max_member_mb> <result_path>"
        )
        return 2
    try:
        run_import(
            request=ImportRequest(
                source=Path(argv[0]),
                data_dir=Path(argv[1]),
                now=datetime.fromisoformat(argv[2]),
                limits=ValidationLimits(member_bytes=int(argv[4]) * BYTES_PER_MB),
            ),
            max_memory_mb=int(argv[3]),
            result_path=Path(argv[5]),
        )
    except MemoryError:
        logger.exception("Package import ran out of memory for %s", argv[0])
        return MEMORY_EXIT_CODE
    except Exception:
        logger.exception("Package import failed for %s", argv[0])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(argv=sys.argv[1:]))

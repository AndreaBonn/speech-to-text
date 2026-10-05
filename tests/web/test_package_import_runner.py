import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from sbobina.course_registry import CourseRecord
from sbobina.package_import import ImportResult, PackageStorageError
from sbobina.package_remap_types import IdMaps, ImportedFrom
from sbobina.package_validate import (
    DEFAULT_LIMITS,
    PackageInvalidError,
    PackageTooLargeError,
)
from sbobina.web import package_import_runner

NOW = datetime(2026, 10, 5, tzinfo=UTC)


@pytest.fixture
def argv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    monkeypatch.setattr(package_import_runner, "_apply_memory_limit", Mock())
    return [
        str(tmp_path / "source.zip"),
        str(tmp_path / "data"),
        NOW.isoformat(),
        "512",
        str(tmp_path / "result.json"),
    ]


def make_result() -> ImportResult:
    return ImportResult(
        course=CourseRecord(
            id="00000000-0000-4000-8000-000000000001",
            key="fisica",
            label="Fisica",
            created_at=NOW,
            updated_at=NOW,
        ),
        imported_from=ImportedFrom(
            package_id="original",
            ids=IdMaps(
                courses={},
                jobs={},
                documents={},
                generations={},
                cards={},
            ),
        ),
        warning=None,
    )


@pytest.mark.parametrize(
    "error,status",
    [
        (PackageInvalidError("Bad archive"), "rejected"),
        (PackageTooLargeError("Archive too large"), "rejected"),
        (PackageStorageError("Disk full"), "storage_error"),
    ],
)
def test_main_mapped_error_writes_result(
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
    error: PackageInvalidError | PackageTooLargeError | PackageStorageError,
    status: str,
) -> None:
    monkeypatch.setattr(
        package_import_runner, "import_package", Mock(side_effect=error)
    )

    exit_code = package_import_runner.main(argv=argv)

    assert exit_code == 0
    assert json.loads(Path(argv[-1]).read_text(encoding="utf-8")) == {
        "status": status,
        "code": error.code,
        "message": str(error),
    }


@pytest.mark.parametrize(
    ("error", "exit_code"),
    [(RuntimeError("Unexpected failure"), 1), (MemoryError("Out of memory"), 3)],
)
def test_main_unmapped_error_returns_one_without_result(
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    exit_code: int,
) -> None:
    # The parent tells memory exhaustion (3) from a crash (1) by exit code.
    imported = Mock(side_effect=[make_result(), error])
    monkeypatch.setattr(package_import_runner, "import_package", imported)
    result_path = Path(argv[-1])
    assert package_import_runner.main(argv=argv) == 0
    assert json.loads(result_path.read_text(encoding="utf-8"))["status"] == "imported"
    result_path.unlink()

    assert package_import_runner.main(argv=argv) == exit_code

    assert not result_path.exists()
    assert str(error) in caplog.text


def test_main_success_applies_limit_before_default_import(
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    limit = Mock(side_effect=lambda max_memory_mb: calls.append("limit"))

    def record_import(**kwargs: object) -> ImportResult:
        calls.append("import")
        return make_result()

    imported = Mock(side_effect=record_import)
    monkeypatch.setattr(package_import_runner, "_apply_memory_limit", limit)
    monkeypatch.setattr(package_import_runner, "import_package", imported)
    exit_code = package_import_runner.main(argv=argv)
    assert exit_code == 0
    assert calls == ["limit", "import"]
    limit.assert_called_once_with(max_memory_mb=512)
    imported.assert_called_once_with(
        source=Path(argv[0]),
        data_dir=Path(argv[1]),
        now=NOW,
        limits=DEFAULT_LIMITS,
    )
    assert json.loads(Path(argv[-1]).read_text(encoding="utf-8")) == {
        "status": "imported",
        "course_id": make_result().course.id,
        "course_label": "Fisica",
        "warning": None,
    }


def test_main_missing_arguments_returns_usage_error(
    argv: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        package_import_runner, "import_package", Mock(return_value=make_result())
    )
    assert package_import_runner.main(argv=argv) == 0
    assert package_import_runner.main(argv=[]) == 2

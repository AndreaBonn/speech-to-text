import json
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.job_models import JobConfig
from sbobina.web.job_store import JobStore
from sbobina.web.package_import_worker import (
    PackageImportOptions,
    PackageImportOutcome,
    PackageImportStatus,
    run_package_import,
)

NOW = datetime(2026, 10, 5, tzinfo=UTC)
IMPORTED = {
    "status": "imported",
    "course_id": "new-course",
    "course_label": "Fisica",
    "warning": "Already imported",
}
FAKE_RUNNER = """
import json
import sys
import time
from pathlib import Path

source, data_dir, now, max_memory_mb, max_member_mb, result_path = sys.argv[1:]
root = Path(source).parent
result = Path(result_path)
(root / "result-path").write_text(result_path)
if (root / "publish").exists():
    course = Path(data_dir) / "courses" / "11111111-1111-4111-8111-111111111111"
    course.mkdir(parents=True)
    (course / "course.json").write_text(json.dumps({
        "id": "11111111-1111-4111-8111-111111111111", "key": "fisica",
        "label": "Fisica", "created_at": now, "updated_at": now,
    }))
    (course / "imported_from.json").write_text("{}")
if (root / "publish-lectures").exists():
    lecture = Path(data_dir) / "jobs" / "44444444-4444-4444-8444-444444444444"
    lecture.mkdir(parents=True)
    (lecture / "job.json").write_text(json.dumps({
        "id": "44444444-4444-4444-8444-444444444444", "status": "done",
        "stage": "done", "config": {}, "created_at": now, "updated_at": now,
        "imported": True, "import_id": "33333333-3333-4333-8333-333333333333",
    }))
if (root / "stage").exists():
    for name in ("courses", "jobs"):
        staging = Path(data_dir) / name / ".import-00000000-0000-4000-8000-000000000001"
        staging.mkdir(parents=True)
        (staging / "partial.json").write_text("{}")
    (root / "staged").touch()
(root / "started").touch()
while (root / "hold").exists():
    time.sleep(0.01)
if (root / "oom").exists():
    import resource
    limit = int(max_memory_mb) * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    (root / "limited").touch()
    try:
        bytearray(limit * 4)
    except MemoryError:
        sys.exit(3)  # as package_import_runner.MEMORY_EXIT_CODE
if (root / "crash").exists():
    print("Traceback: child exploded", file=sys.stderr)
    sys.exit(1)
if (root / "empty").exists():
    sys.exit(0)
if (root / "result-directory").exists():
    result.mkdir()
else:
    result.write_bytes((root / "payload").read_bytes())
(root / "result-written").touch()
sys.exit(3 if (root / "nonzero").exists() else 0)
"""


def wait_for(predicate: Callable[[], bool], timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail("Condition did not become true before timeout")
        time.sleep(0.01)


@dataclass(frozen=True)
class Harness:
    root: Path
    options: PackageImportOptions

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    def run_import(self) -> PackageImportOutcome:
        return run_package_import(
            source=self.root / "input.sbobina.zip",
            data_dir=self.data_dir,
            now=NOW,
            options=self.options,
        )


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    (tmp_path / "fake_package_import_runner.py").write_text(
        data=FAKE_RUNNER, encoding="utf-8"
    )
    (tmp_path / "payload").write_text(data=json.dumps(obj=IMPORTED), encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    return Harness(
        root=tmp_path,
        options=PackageImportOptions(
            command=(sys.executable, "-m", "fake_package_import_runner"),
            timeout_s=5.0,
            max_memory_mb=64,
            terminate_timeout_s=0.1,
        ),
    )


@pytest.mark.skipif(
    sys.platform == "win32", reason="RLIMIT_AS is unavailable on Windows"
)
def test_run_package_import_over_memory_limit_returns_package_failed(
    harness: Harness,
) -> None:
    assert harness.run_import().status == PackageImportStatus.IMPORTED
    (harness.root / "oom").touch()

    outcome = harness.run_import()

    assert (harness.root / "limited").exists()
    assert outcome.status == PackageImportStatus.RESOURCE_EXHAUSTED
    assert outcome.code == "PACKAGE_FAILED"


def test_run_package_import_held_child_keeps_courses_alive(harness: Harness) -> None:
    app = create_app(settings=Settings(), data_dir=harness.data_dir)
    client = TestClient(app=app, base_url="http://127.0.0.1:8765")
    hold = harness.root / "hold"
    hold.touch()
    try:
        assert client.get(url="/api/v1/courses").status_code == 200
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(harness.run_import)
            try:
                wait_for(predicate=(harness.root / "started").exists)
                assert client.get(url="/api/v1/courses").status_code == 200
                assert hold.exists()
                assert not future.done()
            finally:
                hold.unlink(missing_ok=True)
            assert future.result(timeout=5).status == PackageImportStatus.IMPORTED
    finally:
        client.close()


def test_run_package_import_timeout_removes_staging(harness: Harness) -> None:
    normal = harness.data_dir / "courses" / "existing-course"
    normal.mkdir(parents=True)
    (normal / "keep.txt").write_text(data="keep", encoding="utf-8")
    (harness.root / "stage").touch()
    (harness.root / "hold").touch()
    timed = replace(harness, options=replace(harness.options, timeout_s=0.5))

    outcome = timed.run_import()

    assert (harness.root / "staged").exists()
    assert outcome.status == PackageImportStatus.TIMEOUT
    assert outcome.code == "PACKAGE_IMPORT_TIMEOUT"
    assert (normal / "keep.txt").read_text(encoding="utf-8") == "keep"
    for name in ("courses", "jobs"):
        assert (harness.data_dir / name).is_dir()
        assert list((harness.data_dir / name).glob(pattern=".import-*")) == []


@pytest.mark.parametrize("warning", [None, "Already imported"])
def test_run_package_import_success_returns_course(
    harness: Harness, warning: str | None
) -> None:
    (harness.root / "payload").write_text(
        data=json.dumps(obj=IMPORTED | {"warning": warning}), encoding="utf-8"
    )

    outcome = harness.run_import()

    assert outcome == PackageImportOutcome(
        status=PackageImportStatus.IMPORTED,
        course_id="new-course",
        course_label="Fisica",
        warning=warning,
    )
    assert (harness.root / "result-written").exists()
    result_path = Path((harness.root / "result-path").read_text(encoding="utf-8"))
    assert not result_path.exists()


@pytest.mark.parametrize(
    "status,code",
    [
        (PackageImportStatus.REJECTED, "PACKAGE_INVALID"),
        (PackageImportStatus.REJECTED, "PACKAGE_TOO_LARGE"),
        (PackageImportStatus.STORAGE_ERROR, "PACKAGE_STORAGE_FAILED"),
    ],
)
def test_run_package_import_mapped_error_preserves_code(
    harness: Harness,
    status: PackageImportStatus,
    code: str,
) -> None:
    (harness.root / "payload").write_text(
        data=json.dumps(
            obj={
                "status": status,
                "code": code,
                "message": "Import rejected",
            }
        ),
        encoding="utf-8",
    )

    outcome = harness.run_import()

    assert outcome == PackageImportOutcome(
        status=status, code=code, message="Import rejected"
    )
    (harness.root / "crash").touch()
    assert harness.run_import().code == "PACKAGE_IMPORT_FAILED"


@pytest.mark.parametrize(
    "payload",
    [
        b"not JSON",
        b"\xff",
        b"[]",
        b"null",
        b"{}",
        b'{"status":"timeout"}',
        b'{"status":"imported"}',
        b'{"status":"imported","course_id":3,"course_label":"Physics"}',
        b'{"status":"rejected","code":"PACKAGE_INVALID"}',
    ],
)
def test_run_package_import_invalid_result_returns_package_failed(
    harness: Harness,
    payload: bytes,
) -> None:
    assert harness.run_import().status == PackageImportStatus.IMPORTED
    (harness.root / "payload").write_bytes(data=payload)

    outcome = harness.run_import()

    # A malformed result is a bug in the child, never a memory problem.
    assert outcome.status == PackageImportStatus.FAILED
    assert outcome.code == "PACKAGE_IMPORT_FAILED"


def test_run_package_import_crash_copies_child_log_to_server_log(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    # The child's log lives in a temporary directory removed on return.
    (harness.root / "crash").touch()
    assert harness.run_import().status == PackageImportStatus.FAILED
    assert "Import child log" in caplog.text
    assert "Traceback: child exploded" in caplog.text


def test_run_package_import_success_keeps_child_log_out(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    assert harness.run_import().status == PackageImportStatus.IMPORTED
    assert "Import child log" not in caplog.text


@pytest.mark.parametrize("marker", ["crash", "empty", "result-directory"])
def test_run_package_import_missing_or_unreadable_result_returns_package_failed(
    harness: Harness,
    marker: str,
) -> None:
    assert harness.run_import().status == PackageImportStatus.IMPORTED
    (harness.root / marker).touch()

    outcome = harness.run_import()

    assert outcome.status == PackageImportStatus.FAILED
    assert outcome.code == "PACKAGE_IMPORT_FAILED"


def test_run_package_import_valid_result_survives_nonzero_exit(
    harness: Harness,
) -> None:
    (harness.root / "nonzero").touch()

    outcome = harness.run_import()

    assert outcome.status == PackageImportStatus.IMPORTED
    assert outcome.course_id == "new-course"


def test_run_package_import_second_import_while_one_runs_is_busy(
    harness: Harness,
) -> None:
    # The timeout path removes every .import-* directory, which is only safe
    # if no other import is staging at the same time: a second one is refused.
    hold = harness.root / "hold"
    hold.touch()
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(harness.run_import)
        try:
            wait_for(predicate=(harness.root / "started").exists)
            second = harness.run_import()
            assert second.status == PackageImportStatus.BUSY
            assert second.code == "PACKAGE_IMPORT_BUSY"
            assert not first.done()
        finally:
            hold.unlink(missing_ok=True)
        assert first.result(timeout=5).status == PackageImportStatus.IMPORTED

    assert harness.run_import().status == PackageImportStatus.IMPORTED


def test_run_package_import_timeout_after_publish_reports_the_course(
    harness: Harness,
) -> None:
    # Killed after the final rename but before result.json: the course exists,
    # so reporting a timeout would make the student import it twice.
    (harness.root / "publish").touch()
    (harness.root / "hold").touch()
    timed = replace(harness, options=replace(harness.options, timeout_s=0.5))

    outcome = timed.run_import()

    assert outcome.status == PackageImportStatus.IMPORTED
    assert outcome.course_id == "11111111-1111-4111-8111-111111111111"
    assert outcome.course_label == "Fisica"


def test_run_package_import_timeout_before_publish_stays_a_timeout(
    harness: Harness,
) -> None:
    existing = harness.data_dir / "courses" / "22222222-2222-4222-8222-222222222222"
    existing.mkdir(parents=True)
    (existing / "imported_from.json").write_text("{}", encoding="utf-8")
    (harness.root / "hold").touch()
    timed = replace(harness, options=replace(harness.options, timeout_s=0.5))

    outcome = timed.run_import()

    assert outcome.status == PackageImportStatus.TIMEOUT


def test_run_package_import_timeout_between_renames_removes_published_lectures(
    harness: Harness,
) -> None:
    # B7: lectures are renamed in before the course; a kill in between must
    # not leave them on disk until the next server start.
    store = JobStore(data_dir=harness.data_dir)
    kept = store.create(config=JobConfig(), source_name="Lezione")
    (harness.root / "publish-lectures").touch()
    (harness.root / "hold").touch()
    timed = replace(harness, options=replace(harness.options, timeout_s=0.5))

    outcome = timed.run_import()

    assert outcome.status == PackageImportStatus.TIMEOUT
    jobs = sorted(path.name for path in (harness.data_dir / "jobs").iterdir())
    assert jobs == [str(kept.id)]

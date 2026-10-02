import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sbobina.document_models import CourseDocument, DocumentKind, DocumentStatus
from sbobina.web import document_store
from sbobina.web.errors import ConflictError
from sbobina.web.extraction_worker import ExtractionWorker, ExtractionWorkerOptions

# A fake child, in the spirit of test_supervisor.py's RUNNER: touches
# "started" on entry, blocks on "sleep"/"hold", simulates the real runner's
# own RLIMIT_AS + over-allocation on "oom", otherwise writes a minimal
# text.json and exits 0.
FAKE_RUNNER = """
import json
import sys
import time
from pathlib import Path

_, doc_dir, max_memory_mb = sys.argv[1:]
path = Path(doc_dir)
(path / "started").touch()
if (path / "sleep").exists():
    time.sleep(10)
while (path / "hold").exists():
    time.sleep(0.01)
if (path / "oom").exists():
    import resource
    limit = int(max_memory_mb) * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    bytearray(limit * 4)
    sys.exit(0)
(path / "text.json").write_text(json.dumps(
    {"pages": [{"text": "a" * 30, "no_text": False}], "status": "ready", "encoding": None}
))
"""


def wait_for(
    predicate: Callable[[], bool], timeout_s: float = 5, interval_s: float = 0.02
) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail("Condition did not become true before timeout")
        time.sleep(interval_s)


@dataclass
class Harness:
    courses_dir: Path
    worker: ExtractionWorker

    def add_document(
        self, doc_id: str, status: DocumentStatus = DocumentStatus.UPLOADING
    ) -> Path:
        doc_dir = document_store.document_dir(
            courses_dir=self.courses_dir, course_id="course-1", doc_id=doc_id
        )
        doc_dir.mkdir(parents=True)
        document_store.write_document(
            courses_dir=self.courses_dir,
            document=CourseDocument(
                id=doc_id,
                course_id="course-1",
                filename="manual.pdf",
                kind=DocumentKind.PDF,
                size=10,
                sha256="a" * 64,
                status=status,
                error=None,
                pages=None,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )
        return doc_dir

    def status(self, doc_id: str) -> DocumentStatus:
        return document_store.read_document(
            courses_dir=self.courses_dir, course_id="course-1", doc_id=doc_id
        ).status


def _build_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, timeout_s: float
) -> Harness:
    (tmp_path / "fake_extraction_runner.py").write_text(FAKE_RUNNER, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    courses_dir = tmp_path / "courses"
    worker = ExtractionWorker(
        courses_dir=courses_dir,
        options=ExtractionWorkerOptions(
            command=(sys.executable, "-m", "fake_extraction_runner"),
            timeout_s=timeout_s,
            max_memory_mb=64,
            terminate_timeout_s=0.1,
        ),
    )
    return Harness(courses_dir=courses_dir, worker=worker)


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    built = _build_worker(tmp_path=tmp_path, monkeypatch=monkeypatch, timeout_s=0.2)
    try:
        yield built
    finally:
        built.worker.stop()


def test_submit_marks_extracting_immediately(harness: Harness) -> None:
    harness.add_document(doc_id="doc-1")
    harness.worker.submit(course_id="course-1", doc_id="doc-1")
    assert harness.status(doc_id="doc-1") == DocumentStatus.EXTRACTING


def test_successful_extraction_marks_ready(harness: Harness) -> None:
    harness.add_document(doc_id="doc-1")
    harness.worker.start()
    harness.worker.submit(course_id="course-1", doc_id="doc-1")
    wait_for(predicate=lambda: harness.status(doc_id="doc-1") == DocumentStatus.READY)


def test_child_past_timeout_is_killed_and_marked_failed(harness: Harness) -> None:
    doc_dir = harness.add_document(doc_id="doc-1")
    (doc_dir / "sleep").touch()
    harness.worker.start()
    harness.worker.submit(course_id="course-1", doc_id="doc-1")
    wait_for(predicate=lambda: harness.status(doc_id="doc-1") == DocumentStatus.FAILED)
    document = document_store.read_document(
        courses_dir=harness.courses_dir, course_id="course-1", doc_id="doc-1"
    )
    assert document.error == "EXTRACTION_TIMEOUT"


@pytest.mark.skipif(
    sys.platform == "win32", reason="RLIMIT_AS does not exist on Windows"
)
def test_child_over_memory_limit_is_marked_failed(harness: Harness) -> None:
    doc_dir = harness.add_document(doc_id="doc-1")
    (doc_dir / "oom").touch()
    harness.worker.start()
    harness.worker.submit(course_id="course-1", doc_id="doc-1")
    wait_for(predicate=lambda: harness.status(doc_id="doc-1") == DocumentStatus.FAILED)
    document = document_store.read_document(
        courses_dir=harness.courses_dir, course_id="course-1", doc_id="doc-1"
    )
    assert document.error == "EXTRACTION_FAILED"


def test_recover_on_boot_requeues_orphaned_extracting_documents(
    harness: Harness,
) -> None:
    harness.add_document(doc_id="doc-1", status=DocumentStatus.EXTRACTING)
    harness.worker.recover_on_boot()
    harness.worker.start()
    wait_for(predicate=lambda: harness.status(doc_id="doc-1") == DocumentStatus.READY)


def test_extractions_run_one_at_a_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A long timeout here: the point is serialization, not the timeout path
    # exercised by the other tests above.
    harness = _build_worker(tmp_path=tmp_path, monkeypatch=monkeypatch, timeout_s=5.0)
    first_dir = harness.add_document(doc_id="doc-1")
    second_dir = harness.add_document(doc_id="doc-2")
    (first_dir / "hold").touch()
    try:
        harness.worker.start()
        harness.worker.submit(course_id="course-1", doc_id="doc-1")
        harness.worker.submit(course_id="course-1", doc_id="doc-2")
        wait_for(predicate=(first_dir / "started").exists)
        assert not (second_dir / "started").exists()
        (first_dir / "hold").unlink()
        wait_for(predicate=(second_dir / "started").exists)
        wait_for(
            predicate=lambda: harness.status(doc_id="doc-2") == DocumentStatus.READY
        )
    finally:
        harness.worker.stop()


def test_stop_terminates_active_child_and_keeps_document_for_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = _build_worker(tmp_path=tmp_path, monkeypatch=monkeypatch, timeout_s=30)
    doc_dir = built.add_document(doc_id="doc-1")
    (doc_dir / "hold").touch()
    built.worker.start()
    built.worker.submit(course_id="course-1", doc_id="doc-1")
    wait_for(predicate=lambda: (doc_dir / "started").exists())

    started = time.monotonic()
    built.worker.stop()

    assert time.monotonic() - started < 5
    assert not built.worker.is_running()
    # Interrupted, not failed: the next boot re-queues it via recover_on_boot.
    assert built.status(doc_id="doc-1") == DocumentStatus.EXTRACTING


def _uploaded(doc_id: str) -> CourseDocument:
    return CourseDocument(
        id=doc_id,
        course_id="course-1",
        filename="manual.pdf",
        kind=DocumentKind.PDF,
        size=10,
        sha256="a" * 64,
        status=DocumentStatus.UPLOADING,
        error=None,
        pages=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_enqueue_new_persists_extracting_without_an_uploading_window(
    harness: Harness,
) -> None:
    doc_dir = document_store.document_dir(
        courses_dir=harness.courses_dir, course_id="course-1", doc_id="doc-1"
    )
    doc_dir.mkdir(parents=True)
    stored = harness.worker.enqueue_new(document=_uploaded(doc_id="doc-1"))
    assert stored.status == DocumentStatus.EXTRACTING
    assert harness.status(doc_id="doc-1") == DocumentStatus.EXTRACTING


def test_remove_if_idle_refuses_extracting_and_removes_finished(
    harness: Harness,
) -> None:
    busy_dir = harness.add_document(doc_id="busy", status=DocumentStatus.EXTRACTING)
    with pytest.raises(ConflictError):
        harness.worker.remove_if_idle(course_id="course-1", doc_id="busy")
    assert busy_dir.exists()

    idle_dir = harness.add_document(doc_id="idle")
    harness.worker.remove_if_idle(course_id="course-1", doc_id="idle")
    assert not idle_dir.exists()

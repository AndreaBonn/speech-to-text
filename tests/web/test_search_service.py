import os
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Event

import pytest
from conftest import make_segment, make_transcript, make_word

from sbobina.models import save_transcript
from sbobina.web.api_files import TRANSCRIPT_FILES
from sbobina.web.job_store import JobStore
from sbobina.web.search_index import open_index
from sbobina.web.search_service import reconcile, search_session


def write_transcript(directory: Path, text: str, variant: str = "original") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / TRANSCRIPT_FILES[variant]
    transcript = make_transcript(
        segments=[make_segment(words=[make_word(text=text, start=2472.0)])]
    )
    save_transcript(transcript=transcript, path=path)
    return path


def test_reconcile_finds_new_transcript_written_outside_server(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        assert reconcile(store=store, index=index) == 0
        write_transcript(directory=store.jobs_dir / "job", text="contratto")
        assert reconcile(store=store, index=index) == 1
        page = index.search(match='"contratt"*', job_ids=None, limit=10, offset=0)
        assert page.total == 1
        assert page.items[0].start == 2472.0
        assert page.items[0].variant == "original"


def test_reconcile_prefers_corrected_even_with_identical_stat(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    original = write_transcript(directory=store.jobs_dir / "job", text="errato")
    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        assert reconcile(store=store, index=index) == 1
        assert (
            index.search(match='"errato"', job_ids=None, limit=10, offset=0).total == 1
        )
        corrected = write_transcript(
            directory=original.parent, text="giusto", variant="corrected"
        )
        stamp = original.stat().st_mtime_ns
        os.utime(corrected, ns=(stamp, stamp))
        assert corrected.stat().st_size == original.stat().st_size
        assert reconcile(store=store, index=index) == 1
        page = index.search(match='"giusto"', job_ids=None, limit=10, offset=0)
        assert page.total == 1
        assert page.items[0].variant == "corrected"
        assert (
            index.search(match='"errato"', job_ids=None, limit=10, offset=0).total == 0
        )
        corrected.unlink()
        assert reconcile(store=store, index=index) == 1
        assert index.indexed_lectures()["job"].variant == "original"


def test_reconcile_removes_deleted_jobs_and_missing_transcripts(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    for job_id in ("remove", "keep", "missing"):
        write_transcript(directory=store.jobs_dir / job_id, text="causa")
    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        assert reconcile(store=store, index=index) == 3
        shutil.rmtree(path=store.jobs_dir / "remove")
        (store.jobs_dir / "missing" / TRANSCRIPT_FILES["original"]).unlink()
        assert reconcile(store=store, index=index) == 0
        assert set(index.indexed_lectures()) == {"keep"}
        page = index.search(match='"causa"', job_ids=None, limit=10, offset=0)
        assert [hit.job_id for hit in page.items] == ["keep"]


def test_reconcile_unchanged_files_are_not_reindexed(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    write_transcript(directory=store.jobs_dir / "job", text="causa")
    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        assert reconcile(store=store, index=index) == 1
        assert reconcile(store=store, index=index) == 0
        assert (
            index.search(match='"causa"', job_ids=None, limit=10, offset=0).total == 1
        )


@pytest.mark.parametrize("change", ["mtime", "size"])
def test_reconcile_reindexes_when_either_stat_changes(
    tmp_path: Path, change: str
) -> None:
    store = JobStore(data_dir=tmp_path)
    path = write_transcript(directory=store.jobs_dir / "job", text="prima")
    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        assert reconcile(store=store, index=index) == 1
        previous = path.stat()
        replacement = "dopox" if change == "mtime" else "successivamente"
        write_transcript(directory=path.parent, text=replacement)
        stamp = previous.st_mtime_ns + 1 if change == "mtime" else previous.st_mtime_ns
        os.utime(path, ns=(stamp, stamp))
        assert reconcile(store=store, index=index) == 1
        page = index.search(match=f'"{replacement}"', job_ids=None, limit=10, offset=0)
        assert page.total == 1
        assert (
            index.search(match='"prima"', job_ids=None, limit=10, offset=0).total == 0
        )


def test_search_session_reconciles_on_every_request_and_closes_index(
    tmp_path: Path,
) -> None:
    store = JobStore(data_dir=tmp_path)
    path = tmp_path / "search.sqlite3"
    with search_session(store=store, path=path) as index:
        assert index.indexed_lectures() == {}
    write_transcript(directory=store.jobs_dir / "job", text="causa")
    with search_session(store=store, path=path) as index:
        assert (
            index.search(match='"causa"', job_ids=None, limit=10, offset=0).total == 1
        )
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        index.indexed_lectures()


def test_search_session_serializes_reconciliation_and_query(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    path = tmp_path / "search.sqlite3"
    started, entered = Event(), Event()

    def query() -> int:
        started.set()
        with search_session(store=store, path=path) as index:
            entered.set()
            return index.search(match='"causa"', job_ids=None, limit=10, offset=0).total

    with ThreadPoolExecutor(max_workers=1) as executor:
        with search_session(store=store, path=path):
            future = executor.submit(query)
            assert started.wait(timeout=2)
            assert not entered.wait(timeout=0.1)
            write_transcript(directory=store.jobs_dir / "job", text="causa")
        assert future.result(timeout=2) == 1
        assert entered.is_set()


def test_search_session_releases_lock_after_error(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    path = tmp_path / "search.sqlite3"
    with (
        pytest.raises(ValueError, match="consumer failure"),
        search_session(store=store, path=path),
    ):
        raise ValueError("consumer failure")
    with search_session(store=store, path=path) as index:
        assert index.indexed_lectures() == {}


def test_search_recovers_internal_fts_corruption_from_source_files(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from sbobina.web.search_service import SearchQuery, search

    store = JobStore(data_dir=tmp_path)
    path = tmp_path / "search.sqlite3"
    write_transcript(directory=store.jobs_dir / "job", text="causa")
    query = SearchQuery(match='"causa"', job_ids={"job"}, limit=1, offset=0)
    assert search(store=store, path=path, query=query).total == 1
    with closing(sqlite3.connect(database=path)) as connection, connection:
        connection.execute("UPDATE passages_data SET block = x'00010203' WHERE id > 10")
    page = search(store=store, path=path, query=query)
    assert page.total == 1
    assert page.items[0].start == 2472.0
    assert "ricostru" in caplog.text.lower()


@pytest.mark.parametrize("broken", ['{"source": "a", "segm', '{"source": "a"}', "[]"])
def test_reconcile_skips_an_unreadable_transcript_and_keeps_the_others(
    tmp_path: Path, broken: str, caplog: pytest.LogCaptureFixture
) -> None:
    store = JobStore(data_dir=tmp_path)
    write_transcript(directory=store.jobs_dir / "good", text="contratto")
    bad = write_transcript(directory=store.jobs_dir / "bad", text="causa")
    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        assert reconcile(store=store, index=index) == 2
        bad.write_text(broken, encoding="utf-8")

        assert reconcile(store=store, index=index) == 0

        search = index.search
        assert search(match='"contratt"*', job_ids=None, limit=10, offset=0).total == 1
        # The half-written lecture keeps its last good rows until it is readable.
        assert search(match='"causa"', job_ids=None, limit=10, offset=0).total == 1
        assert "bad" in caplog.text
        write_transcript(directory=bad.parent, text="illecita")
        assert reconcile(store=store, index=index) == 1
        assert search(match='"illecita"', job_ids=None, limit=10, offset=0).total == 1

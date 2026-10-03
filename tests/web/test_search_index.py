import logging
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from sbobina.search_text import Passage, SnippetPart
from sbobina.web.search_index import (
    SCHEMA_VERSION,
    LectureState,
    SearchIndex,
    SearchUnavailableError,
    open_index,
)

STATE = LectureState(variant="original", path_mtime_ns=123, path_size=456)
PASSAGE = Passage(
    segment_index=7, start=2472.0, text="la causa del contratto è illecita perché sì"
)


@pytest.fixture
def index(tmp_path: Path) -> Iterator[SearchIndex]:
    with closing(open_index(path=tmp_path / "search.sqlite3")) as index:
        yield index


def test_search_returns_timestamp_and_highlight(index: SearchIndex) -> None:
    index.replace_lecture(job_id="job", state=STATE, passages=[PASSAGE])
    page = index.search(match='"contratt"*', job_ids=None, limit=10, offset=0)
    assert page.total == 1
    assert page.items[0].start == 2472.0
    assert page.items[0].segment_index == 7
    assert page.items[0].variant == "original"
    assert page.items[0].snippet == [
        SnippetPart(text="la causa del ", match=False),
        SnippetPart(text="contratto", match=True),
        SnippetPart(text=" è illecita perché sì", match=False),
    ]
    accented = index.search(match='"perche"*', job_ids=None, limit=10, offset=0)
    assert accented.total == 1
    assert [part.text for part in accented.items[0].snippet if part.match] == ["perché"]


def test_replace_lecture_is_persistent_and_has_no_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "search.sqlite3"
    corrected = LectureState(variant="corrected", path_mtime_ns=789, path_size=999)
    with closing(open_index(path=path)) as index:
        index.replace_lecture(job_id="job", state=STATE, passages=[PASSAGE])
        index.replace_lecture(job_id="job", state=corrected, passages=[PASSAGE])
    with closing(open_index(path=path)) as index:
        assert index.indexed_lectures() == {"job": corrected}
        page = index.search(match='"contratt"*', job_ids=None, limit=10, offset=0)
        assert page.total == 1
        assert page.items[0].variant == "corrected"


def test_search_filters_bound_job_ids_and_paginates(index: SearchIndex) -> None:
    identifiers = ["a", "b", "x') OR 1=1 --"]
    for job_id in identifiers:
        index.replace_lecture(job_id=job_id, state=STATE, passages=[PASSAGE])
    page = index.search(match='"causa"', job_ids=None, limit=1, offset=1)
    assert page.total == 3
    assert [hit.job_id for hit in page.items] == ["b"]
    page = index.search(match='"causa"', job_ids={identifiers[-1]}, limit=10, offset=0)
    assert [hit.job_id for hit in page.items] == [identifiers[-1]]
    assert page.total == 1
    empty = index.search(match='"causa"', job_ids=set(), limit=10, offset=0)
    assert (empty.items, empty.total) == ([], 0)
    beyond = index.search(match='"causa"', job_ids=None, limit=10, offset=3)
    assert (beyond.items, beyond.total) == ([], 3)


def test_remove_lecture_removes_only_its_passages(index: SearchIndex) -> None:
    for job_id in ("keep", "remove"):
        index.replace_lecture(job_id=job_id, state=STATE, passages=[PASSAGE])
    index.remove_lecture(job_id="remove")
    index.remove_lecture(job_id="remove")
    assert index.indexed_lectures() == {"keep": STATE}
    page = index.search(match='"causa"', job_ids=None, limit=10, offset=0)
    assert [hit.job_id for hit in page.items] == ["keep"]
    assert page.total == 1


def test_replace_lecture_empty_transcript_removes_old_passages(
    index: SearchIndex,
) -> None:
    index.replace_lecture(job_id="job", state=STATE, passages=[PASSAGE])
    assert index.search(match='"causa"', job_ids=None, limit=10, offset=0).total == 1
    index.replace_lecture(job_id="job", state=STATE, passages=[])
    assert index.search(match='"causa"', job_ids=None, limit=10, offset=0).total == 0
    assert index.indexed_lectures() == {"job": STATE}


@pytest.mark.parametrize("version", [0, SCHEMA_VERSION + 1])
def test_open_index_rebuilds_wrong_version(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, version: int
) -> None:
    path = tmp_path / "search.sqlite3"
    with closing(sqlite3.connect(database=path)) as connection:
        connection.execute("CREATE TABLE obsolete (value TEXT)")
        connection.execute(f"PRAGMA user_version = {version}")
    with caplog.at_level(logging.WARNING), closing(open_index(path=path)) as index:
        assert index.indexed_lectures() == {}
    with closing(sqlite3.connect(database=path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = ?", ("obsolete",)
            ).fetchall()
            == []
        )
    assert "ricostru" in caplog.text.lower()


def test_open_index_rebuilds_corrupt_file_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "search.sqlite3"
    path.write_bytes(bytes(range(256)) * 16)
    with caplog.at_level(logging.WARNING), closing(open_index(path=path)) as index:
        index.replace_lecture(job_id="job", state=STATE, passages=[PASSAGE])
        assert index.search(match='"causa"', job_ids=None, limit=1, offset=0).total == 1
    assert "ricostru" in caplog.text.lower()


def test_open_index_reports_missing_fts5(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_connect = sqlite3.connect

    class NoFtsConnection(sqlite3.Connection):
        def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
            if sql.startswith("CREATE VIRTUAL TABLE"):
                raise sqlite3.OperationalError("no such module: fts5")
            return super().execute(sql, parameters)

    def connect(database: Path) -> sqlite3.Connection:
        return real_connect(database=database, factory=NoFtsConnection)

    monkeypatch.setattr(sqlite3, "connect", connect)
    with pytest.raises(SearchUnavailableError, match="FTS5"):
        open_index(path=tmp_path / "search.sqlite3")


def test_replace_lecture_rolls_back_on_write_failure(
    index: SearchIndex, tmp_path: Path
) -> None:
    index.replace_lecture(job_id="job", state=STATE, passages=[PASSAGE])
    with closing(sqlite3.connect(database=tmp_path / "search.sqlite3")) as connection:
        connection.execute(
            "CREATE TRIGGER fail_insert BEFORE INSERT ON lectures "
            "BEGIN SELECT RAISE(ABORT, 'write failed'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="write failed"):
        index.replace_lecture(job_id="job", state=STATE, passages=[])
    assert index.indexed_lectures() == {"job": STATE}
    assert index.search(match='"causa"', job_ids=None, limit=10, offset=0).total == 1


def test_search_ranks_by_relevance_before_job_id(index: SearchIndex) -> None:
    for job_id, text in [("a", "causa " + "altro " * 40), ("z", "causa causa")]:
        index.replace_lecture(
            job_id=job_id,
            state=STATE,
            passages=[Passage(segment_index=0, start=0.0, text=text)],
        )
    page = index.search(match='"causa"', job_ids=None, limit=10, offset=0)
    assert [hit.job_id for hit in page.items] == ["z", "a"]


def test_index_session_discards_corrupt_fts_pages(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from sbobina.web.search_index import SearchCorruptError, index_session

    path = tmp_path / "search.sqlite3"
    with index_session(path=path) as index:
        index.replace_lecture(job_id="job", state=STATE, passages=[PASSAGE])
        assert index.search(match='"causa"', job_ids=None, limit=1, offset=0).total == 1
    with closing(sqlite3.connect(database=path)) as connection, connection:
        connection.execute("UPDATE passages_data SET block = x'00010203' WHERE id > 10")
    with (
        caplog.at_level(logging.WARNING),
        pytest.raises(SearchCorruptError),
        index_session(path=path) as index,
    ):
        index.search(match='"causa"', job_ids=None, limit=1, offset=0)
    assert "ricostru" in caplog.text.lower()
    with index_session(path=path) as index:
        assert index.indexed_lectures() == {}


def test_open_index_does_not_discard_database_on_lock_error(tmp_path: Path) -> None:
    path = tmp_path / "search.sqlite3"
    with closing(open_index(path=path)) as index:
        index.replace_lecture(job_id="job", state=STATE, passages=[PASSAGE])
    with closing(sqlite3.connect(database=path)) as connection:
        connection.execute("BEGIN EXCLUSIVE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            open_index(path=path)
        connection.rollback()
    with closing(open_index(path=path)) as index:
        assert index.indexed_lectures() == {"job": STATE}


def test_search_returns_more_than_three_passages_per_lecture(
    index: SearchIndex,
) -> None:
    passages = [
        Passage(segment_index=number, start=float(number), text="causa")
        for number in range(5)
    ]
    index.replace_lecture(job_id="job", state=STATE, passages=passages)
    page = index.search(match='"causa"', job_ids=None, limit=10, offset=0)
    assert page.total == 5
    assert [hit.segment_index for hit in page.items] == list(range(5))


def _passages(count: int, text: str) -> list[Passage]:
    return [Passage(segment_index=i, start=float(i), text=text) for i in range(count)]


def test_search_lectures_counts_every_lecture_past_a_thousand_passages(
    index: SearchIndex,
) -> None:
    index.replace_lecture(
        job_id="dense", state=STATE, passages=_passages(1100, "contratto contratto")
    )
    index.replace_lecture(
        job_id="sparse",
        state=STATE,
        passages=_passages(1, "il contratto e poi molte altre parole diverse"),
    )

    first = index.search_lectures(match='"contratt"*', job_ids=None, page=(1, 0))
    second = index.search_lectures(match='"contratt"*', job_ids=None, page=(1, 1))

    assert first.total == 2
    assert [hit.job_id for hit in first.items] == ["dense"]
    assert first.items[0].passage_count == 1100
    assert [hit.job_id for hit in second.items] == ["sparse"]
    assert second.items[0].passage_count == 1


def test_search_lectures_respects_job_ids_and_misses(index: SearchIndex) -> None:
    index.replace_lecture(job_id="a", state=STATE, passages=_passages(2, "contratto"))
    index.replace_lecture(job_id="b", state=STATE, passages=_passages(2, "contratto"))

    page = index.search_lectures(match='"contratt"*', job_ids=["b"], page=(10, 0))
    missing = index.search_lectures(match='"assente"', job_ids=None, page=(10, 0))

    assert [hit.job_id for hit in page.items] == ["b"]
    assert page.total == 1
    assert missing.items == []
    assert missing.total == 0


def test_index_session_propagates_non_corruption_errors_and_keeps_the_index(
    tmp_path: Path,
) -> None:
    from sbobina.web.search_index import index_session

    path = tmp_path / "search.sqlite3"
    with index_session(path=path) as index:
        index.replace_lecture(job_id="job", state=STATE, passages=[PASSAGE])

    with pytest.raises(sqlite3.OperationalError), index_session(path=path) as index:
        index.search(match='"non chiusa', job_ids=None, limit=1, offset=0)

    with index_session(path=path) as index:
        assert set(index.indexed_lectures()) == {"job"}

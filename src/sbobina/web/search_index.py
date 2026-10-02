import logging
import sqlite3
from collections.abc import Collection, Iterable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from sbobina.search_text import (
    MATCH_END,
    MATCH_START,
    Passage,
    SnippetPart,
    snippet_parts,
)
from sbobina.web.errors import AppError

logger = logging.getLogger(__name__)
SCHEMA_VERSION = 1
Variant = Literal["original", "corrected"]
CORRUPTION_CODES = {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}
PRIMARY_ERROR_MASK = 0xFF


class SearchUnavailableError(AppError):
    """The SQLite runtime cannot provide full-text search."""


class SearchCorruptError(AppError):
    """Corrupt derived data was discarded; reconcile from source files again."""


class _SchemaMismatch(Exception):
    pass


@dataclass(frozen=True)
class LectureState:
    variant: Variant
    path_mtime_ns: int
    path_size: int


@dataclass(frozen=True)
class SearchHit:
    job_id: str
    variant: Variant
    segment_index: int
    start: float
    snippet: list[SnippetPart]


@dataclass(frozen=True)
class SearchPage:
    items: list[SearchHit]
    total: int


def _create_schema(connection: sqlite3.Connection) -> None:
    """Use accent-insensitive Unicode tokens and three-character prefix indexes.

    See https://www.sqlite.org/fts5.html#unicode61_tokenizer and
    https://www.sqlite.org/fts5.html#prefix_indexes.
    """
    connection.execute(
        "CREATE TABLE IF NOT EXISTS lectures (job_id TEXT PRIMARY KEY, "
        "variant TEXT NOT NULL, path_mtime_ns INTEGER NOT NULL, "
        "path_size INTEGER NOT NULL, indexed_at TEXT NOT NULL)"
    )
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5("
            "text, job_id UNINDEXED, segment_index UNINDEXED, start UNINDEXED, "
            "tokenize='unicode61 remove_diacritics 2', prefix='3')"
        )
    except sqlite3.OperationalError as error:
        if "no such module: fts5" not in str(error).lower():
            raise
        raise SearchUnavailableError(
            message="SQLite FTS5 is unavailable", code="SEARCH_UNAVAILABLE"
        ) from error
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _connect(path: Path) -> sqlite3.Connection:
    is_existing = path.exists()
    connection = sqlite3.connect(database=path)
    connection.row_factory = sqlite3.Row
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if is_existing and version != SCHEMA_VERSION:
            raise _SchemaMismatch(
                f"Schema version {version}, expected {SCHEMA_VERSION}"
            )
        with connection:
            _create_schema(connection=connection)
    except Exception:
        connection.close()
        raise
    return connection


def open_index(path: Path) -> "SearchIndex":
    """Open one request's connection; rebuild incompatible or corrupt derived data.

    The caller must serialize opening, reconciliation and querying, then close
    the returned index before releasing the service lock.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        connection = _connect(path=path)
    except (_SchemaMismatch, sqlite3.DatabaseError) as error:
        if (
            isinstance(error, sqlite3.DatabaseError)
            and error.sqlite_errorcode & PRIMARY_ERROR_MASK not in CORRUPTION_CODES
        ):
            raise
        logger.warning("Indice di ricerca da ricostruire: %s (%s)", path, error)
        path.unlink(missing_ok=True)
        connection = _connect(path=path)
    return SearchIndex(connection=connection)


@contextmanager
def index_session(path: Path) -> Iterator["SearchIndex"]:
    """Discard corruption discovered during reads without scanning FTS on every open."""
    try:
        with closing(open_index(path=path)) as index:
            yield index
    except sqlite3.DatabaseError as error:
        if error.sqlite_errorcode & PRIMARY_ERROR_MASK not in CORRUPTION_CODES:
            raise
        logger.warning(
            "Indice di ricerca corrotto, da ricostruire: %s (%s)", path, error
        )
        path.unlink(missing_ok=True)
        raise SearchCorruptError(
            message="Search index corruption requires reconciliation",
            code="SEARCH_CORRUPT",
        ) from error


def _search_filter(
    match: str, job_ids: Collection[str] | None
) -> tuple[str, list[object]]:
    clause = "passages MATCH ?"
    parameters: list[object] = [match]
    if job_ids is not None:
        placeholders = ", ".join("?" for _ in job_ids)
        clause += f" AND passages.job_id IN ({placeholders})"
        parameters.extend(job_ids)
    return clause, parameters


def _search_hit(row: sqlite3.Row) -> SearchHit:
    return SearchHit(
        job_id=row["job_id"],
        variant=cast(Variant, row["variant"]),
        segment_index=row["segment_index"],
        start=row["start"],
        snippet=snippet_parts(highlighted=row["highlighted"]),
    )


class SearchIndex:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def close(self) -> None:
        self._connection.close()

    def replace_lecture(
        self, job_id: str, state: LectureState, passages: Iterable[Passage]
    ) -> None:
        with self._connection:
            self._delete_lecture(job_id=job_id)
            self._connection.execute(
                "INSERT INTO lectures "
                "(job_id, variant, path_mtime_ns, path_size, indexed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    job_id,
                    state.variant,
                    state.path_mtime_ns,
                    state.path_size,
                    datetime.now(tz=UTC).isoformat(),
                ),
            )
            self._connection.executemany(
                "INSERT INTO passages (text, job_id, segment_index, start) "
                "VALUES (?, ?, ?, ?)",
                ((p.text, job_id, p.segment_index, p.start) for p in passages),
            )

    def _delete_lecture(self, job_id: str) -> None:
        self._connection.execute("DELETE FROM passages WHERE job_id = ?", (job_id,))
        self._connection.execute("DELETE FROM lectures WHERE job_id = ?", (job_id,))

    def remove_lecture(self, job_id: str) -> None:
        with self._connection:
            self._delete_lecture(job_id=job_id)

    def indexed_lectures(self) -> dict[str, LectureState]:
        rows = self._connection.execute(
            "SELECT job_id, variant, path_mtime_ns, path_size FROM lectures"
        )
        return {
            row["job_id"]: LectureState(
                variant=cast(Variant, row["variant"]),
                path_mtime_ns=row["path_mtime_ns"],
                path_size=row["path_size"],
            )
            for row in rows
        }

    def search(
        self, match: str, job_ids: Collection[str] | None, limit: int, offset: int
    ) -> SearchPage:
        """Return raw passages, ranked by bm25 (lower scores rank first).

        https://www.sqlite.org/fts5.html#the_bm25_function
        MATCH must come from build_match_query, never directly from user input:
        https://www.sqlite.org/fts5.html#full_text_query_syntax.
        """
        clause, parameters = _search_filter(match=match, job_ids=job_ids)
        total = self._connection.execute(
            f"SELECT count(*) FROM passages WHERE {clause}", parameters
        ).fetchone()[0]
        rows = self._select_hits(
            clause=clause, parameters=parameters, page=(limit, offset)
        )
        return SearchPage(items=[_search_hit(row=row) for row in rows], total=total)

    def _select_hits(
        self, clause: str, parameters: list[object], page: tuple[int, int]
    ) -> sqlite3.Cursor:
        """Mark matches with PUA delimiters, leaving literal HTML as plain text.

        See https://www.sqlite.org/fts5.html#the_highlight_function.
        """
        return self._connection.execute(
            "SELECT passages.job_id, lectures.variant, segment_index, start, "
            "highlight(passages, 0, ?, ?) AS highlighted "
            "FROM passages JOIN lectures ON lectures.job_id = passages.job_id "
            f"WHERE {clause} ORDER BY bm25(passages), passages.job_id, segment_index "
            "LIMIT ? OFFSET ?",
            [MATCH_START, MATCH_END, *parameters, *page],
        )

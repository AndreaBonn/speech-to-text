import logging
import sqlite3
from collections.abc import Collection, Iterable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from sbobina.document_passages import DocumentPassage
from sbobina.search_text import (
    MATCH_END,
    MATCH_START,
    Passage,
    snippet_parts,
)
from sbobina.web import document_index
from sbobina.web.document_index import (
    DocumentScope,
    DocumentSearchPage,
    DocumentState,
    RankedDocumentPassage,
)
from sbobina.web.search_schema import (
    CORRUPTION_CODES,
    PRIMARY_ERROR_MASK,
    SCHEMA_VERSION,
    LectureHit,
    LecturePage,
    LectureState,
    SchemaMismatchError,
    SearchCorruptError,
    SearchHit,
    SearchPage,
    SearchUnavailableError,
    Variant,
    connect_index,
)

# Schema names stay importable from here: callers predate the split.
__all__ = [
    "SCHEMA_VERSION",
    "DocumentSearchPage",
    "DocumentState",
    "LectureHit",
    "LecturePage",
    "LectureState",
    "SearchCorruptError",
    "SearchHit",
    "SearchIndex",
    "SearchPage",
    "SearchUnavailableError",
    "Variant",
    "index_session",
    "open_index",
]

logger = logging.getLogger(__name__)


def open_index(path: Path) -> "SearchIndex":
    """Open one request's connection; rebuild incompatible or corrupt derived data.

    The caller must serialize opening, reconciliation and querying, then close
    the returned index before releasing the service lock.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        connection = connect_index(path=path)
    except (SchemaMismatchError, sqlite3.DatabaseError) as error:
        if (
            isinstance(error, sqlite3.DatabaseError)
            and error.sqlite_errorcode & PRIMARY_ERROR_MASK not in CORRUPTION_CODES
        ):
            raise
        logger.warning("Indice di ricerca da ricostruire: %s (%s)", path, error)
        path.unlink(missing_ok=True)
        connection = connect_index(path=path)
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


@dataclass(frozen=True)
class RankedLecturePassage:
    """One passages row with its full text and bm25 score, for retrieval."""

    job_id: str
    segment_index: int
    start: float
    text: str
    score: float


def _ranked_lecture_passage(row: sqlite3.Row) -> RankedLecturePassage:
    return RankedLecturePassage(
        job_id=row["job_id"],
        segment_index=row["segment_index"],
        start=row["start"],
        text=row["text"],
        score=row["score"],
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

    def search_lectures(
        self, match: str, job_ids: Collection[str] | None, page: tuple[int, int]
    ) -> LecturePage:
        """Page lectures by their best passage, counting every match in each.

        bm25() is not allowed inside an aggregate, so a MATERIALIZED CTE scores
        the passages first. page is (limit, offset) over lectures, not passages.
        """
        clause, parameters = _search_filter(match=match, job_ids=job_ids)
        scored = (
            "WITH scored AS MATERIALIZED (SELECT passages.job_id AS job_id, "
            f"bm25(passages) AS score FROM passages WHERE {clause}) "
        )
        total = self._connection.execute(
            scored + "SELECT count(DISTINCT job_id) FROM scored", parameters
        ).fetchone()[0]
        rows = self._connection.execute(
            scored + "SELECT job_id, count(*) AS hits, min(score) AS best FROM scored "
            "GROUP BY job_id ORDER BY best, job_id LIMIT ? OFFSET ?",
            [*parameters, *page],
        )
        items = [
            LectureHit(job_id=row["job_id"], passage_count=row["hits"]) for row in rows
        ]
        return LecturePage(items=items, total=total)

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

    def replace_document(
        self, doc_id: str, state: DocumentState, passages: Iterable[DocumentPassage]
    ) -> None:
        document_index.replace_document(
            connection=self._connection, doc_id=doc_id, state=state, passages=passages
        )

    def remove_document(self, doc_id: str) -> None:
        document_index.remove_document(connection=self._connection, doc_id=doc_id)

    def indexed_documents(self) -> dict[str, DocumentState]:
        return document_index.indexed_documents(connection=self._connection)

    def search_documents(
        self, match: str, course_id: str | None, limit: int, offset: int
    ) -> DocumentSearchPage:
        return document_index.search_documents(
            connection=self._connection,
            match=match,
            course_id=course_id,
            limit=limit,
            offset=offset,
        )

    def lecture_passages_for_retrieval(
        self, match: str, job_ids: Collection[str], limit: int
    ) -> list[RankedLecturePassage]:
        """Full text and bm25 score, best first, for retrieval.py (adr.md § D2)."""
        clause, parameters = _search_filter(match=match, job_ids=job_ids)
        rows = self._connection.execute(
            "SELECT passages.job_id, segment_index, start, text, "
            f"bm25(passages) AS score FROM passages WHERE {clause} "
            "ORDER BY score LIMIT ?",
            [*parameters, limit],
        )
        return [_ranked_lecture_passage(row=row) for row in rows]

    def document_passages_for_retrieval(
        self, match: str, scope: DocumentScope, limit: int
    ) -> list[RankedDocumentPassage]:
        return document_index.ranked_document_passages(
            connection=self._connection, match=match, scope=scope, limit=limit
        )

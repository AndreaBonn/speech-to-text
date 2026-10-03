"""Document passage storage, reconciliation state and search in the FTS5 index.

Split out of search_index.py (T021) to keep that module under the size limit.
Schema: see specs/001-course-workspace/adr.md § D2 and search_schema.py.
"""

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sbobina.document_passages import DocumentPassage
from sbobina.search_text import MATCH_END, MATCH_START, SnippetPart, snippet_parts

SNIPPET_TOKENS = 32
SNIPPET_ELLIPSIS = "…"


@dataclass(frozen=True)
class DocumentState:
    course_id: str
    text_mtime_ns: int
    text_size: int


@dataclass(frozen=True)
class DocumentHit:
    doc_id: str
    course_id: str
    page: int
    chunk: int
    snippet: list[SnippetPart]


@dataclass(frozen=True)
class DocumentSearchPage:
    items: list[DocumentHit]
    total: int


@dataclass(frozen=True)
class RankedDocumentPassage:
    """One doc_passages row with its full text and bm25 score, for retrieval."""

    doc_id: str
    page: int
    chunk: int
    passage_id: str
    text: str
    score: float


def _delete_document(connection: sqlite3.Connection, doc_id: str) -> None:
    connection.execute("DELETE FROM doc_passages WHERE doc_id = ?", (doc_id,))
    connection.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))


def replace_document(
    connection: sqlite3.Connection,
    doc_id: str,
    state: DocumentState,
    passages: Iterable[DocumentPassage],
) -> None:
    with connection:
        _delete_document(connection=connection, doc_id=doc_id)
        connection.execute(
            "INSERT INTO documents "
            "(doc_id, course_id, text_mtime_ns, text_size, indexed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                doc_id,
                state.course_id,
                state.text_mtime_ns,
                state.text_size,
                datetime.now(tz=UTC).isoformat(),
            ),
        )
        connection.executemany(
            "INSERT INTO doc_passages "
            "(text, passage_id, course_id, doc_id, page, chunk) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                (p.text, p.passage_id, state.course_id, doc_id, p.page, p.chunk)
                for p in passages
            ),
        )


def remove_document(connection: sqlite3.Connection, doc_id: str) -> None:
    with connection:
        _delete_document(connection=connection, doc_id=doc_id)


def indexed_documents(connection: sqlite3.Connection) -> dict[str, DocumentState]:
    rows = connection.execute(
        "SELECT doc_id, course_id, text_mtime_ns, text_size FROM documents"
    )
    return {
        row["doc_id"]: DocumentState(
            course_id=row["course_id"],
            text_mtime_ns=row["text_mtime_ns"],
            text_size=row["text_size"],
        )
        for row in rows
    }


def search_documents(
    connection: sqlite3.Connection,
    match: str,
    course_id: str | None,
    limit: int,
    offset: int,
) -> DocumentSearchPage:
    """Return raw passages, ranked by bm25 (lower scores first).

    course_id=None searches every course (the API's un-filtered search).
    MATCH must come from build_match_query, never directly from user input:
    https://www.sqlite.org/fts5.html#full_text_query_syntax.
    """
    clause = "doc_passages MATCH ?"
    parameters: list[object] = [match]
    if course_id is not None:
        clause += " AND doc_passages.course_id = ?"
        parameters.append(course_id)
    total = connection.execute(
        f"SELECT count(*) FROM doc_passages WHERE {clause}", parameters
    ).fetchone()[0]
    rows = connection.execute(
        # A document passage is a whole page: snippet() keeps the matched
        # region only, where lectures (one short segment each) use highlight().
        # https://www.sqlite.org/fts5.html#the_snippet_function
        "SELECT doc_id, course_id, page, chunk, "
        "snippet(doc_passages, 0, ?, ?, ?, ?) AS highlighted FROM doc_passages "
        f"WHERE {clause} ORDER BY bm25(doc_passages), doc_id, page, chunk "
        "LIMIT ? OFFSET ?",
        [
            MATCH_START,
            MATCH_END,
            SNIPPET_ELLIPSIS,
            SNIPPET_TOKENS,
            *parameters,
            limit,
            offset,
        ],
    )
    items = [
        DocumentHit(
            doc_id=row["doc_id"],
            course_id=row["course_id"],
            page=row["page"],
            chunk=row["chunk"],
            snippet=snippet_parts(highlighted=row["highlighted"]),
        )
        for row in rows
    ]
    return DocumentSearchPage(items=items, total=total)


@dataclass(frozen=True)
class DocumentScope:
    course_id: str
    doc_ids: frozenset[str] | None = None


@dataclass(frozen=True)
class CourseDocumentPassage:
    """One doc_passages row with its full text, in reading order (no score).

    For sbobina.web.course_retrieval.sample_course, which groups a course's
    documents into sources for source_sampling.sample_across_sources: there
    is no question to rank against, just the material in reading order.
    """

    doc_id: str
    page: int
    chunk: int
    passage_id: str
    text: str


def course_document_passages(
    connection: sqlite3.Connection, scope: DocumentScope
) -> list[CourseDocumentPassage]:
    """Every passage of one course's documents, ordered by doc_id, page, chunk."""
    clause = "course_id = ?"
    parameters: list[object] = [scope.course_id]
    if scope.doc_ids is not None:
        clause += f" AND doc_id IN ({', '.join('?' for _ in scope.doc_ids)})"
        parameters.extend(scope.doc_ids)
    rows = connection.execute(
        "SELECT doc_id, page, chunk, passage_id, text FROM doc_passages "
        f"WHERE {clause} ORDER BY doc_id, page, chunk",
        parameters,
    )
    return [
        CourseDocumentPassage(
            doc_id=row["doc_id"],
            page=row["page"],
            chunk=row["chunk"],
            passage_id=row["passage_id"],
            text=row["text"],
        )
        for row in rows
    ]


def ranked_document_passages(
    connection: sqlite3.Connection, match: str, scope: DocumentScope, limit: int
) -> list[RankedDocumentPassage]:
    """Full text and bm25 score of one course's passages, best first.

    For retrieval (T023), which needs the whole passage rather than a
    highlighted snippet and a score comparable across the lecture and
    document FTS tables for fusion. See adr.md § D2.
    """
    # The document filter sits before LIMIT: applied afterwards, a selected
    # document outranked by others in the course would vanish.
    clause = "doc_passages MATCH ? AND course_id = ?"
    parameters: list[object] = [match, scope.course_id]
    if scope.doc_ids is not None:
        clause += f" AND doc_id IN ({', '.join('?' for _ in scope.doc_ids)})"
        parameters.extend(scope.doc_ids)
    rows = connection.execute(
        "SELECT doc_id, page, chunk, passage_id, text, bm25(doc_passages) AS score "
        f"FROM doc_passages WHERE {clause} ORDER BY score LIMIT ?",
        [*parameters, limit],
    )
    return [
        RankedDocumentPassage(
            doc_id=row["doc_id"],
            page=row["page"],
            chunk=row["chunk"],
            passage_id=row["passage_id"],
            text=row["text"],
            score=row["score"],
        )
        for row in rows
    ]


class DocumentIndexMixin:
    """SearchIndex's document-table methods, split out to keep that file under
    the size limit (T021): SearchIndex(DocumentIndexMixin) gets these for free.
    """

    _connection: sqlite3.Connection

    def replace_document(
        self, doc_id: str, state: DocumentState, passages: Iterable[DocumentPassage]
    ) -> None:
        replace_document(
            connection=self._connection, doc_id=doc_id, state=state, passages=passages
        )

    def remove_document(self, doc_id: str) -> None:
        remove_document(connection=self._connection, doc_id=doc_id)

    def indexed_documents(self) -> dict[str, DocumentState]:
        return indexed_documents(connection=self._connection)

    def search_documents(
        self, match: str, course_id: str | None, limit: int, offset: int
    ) -> DocumentSearchPage:
        return search_documents(
            connection=self._connection,
            match=match,
            course_id=course_id,
            limit=limit,
            offset=offset,
        )

    def document_passages_for_retrieval(
        self, match: str, scope: DocumentScope, limit: int
    ) -> list[RankedDocumentPassage]:
        return ranked_document_passages(
            connection=self._connection, match=match, scope=scope, limit=limit
        )

    def course_document_passages(
        self, scope: DocumentScope
    ) -> list[CourseDocumentPassage]:
        return course_document_passages(connection=self._connection, scope=scope)

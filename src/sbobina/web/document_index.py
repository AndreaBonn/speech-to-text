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
    course_id: str,
    limit: int,
    offset: int,
) -> DocumentSearchPage:
    """Return raw passages of one course, ranked by bm25 (lower scores first).

    MATCH must come from build_match_query, never directly from user input:
    https://www.sqlite.org/fts5.html#full_text_query_syntax.
    """
    clause = "doc_passages MATCH ? AND doc_passages.course_id = ?"
    parameters: list[object] = [match, course_id]
    total = connection.execute(
        f"SELECT count(*) FROM doc_passages WHERE {clause}", parameters
    ).fetchone()[0]
    rows = connection.execute(
        "SELECT doc_id, page, chunk, "
        f"highlight(doc_passages, 0, ?, ?) AS highlighted FROM doc_passages "
        f"WHERE {clause} ORDER BY bm25(doc_passages), doc_id, page, chunk "
        "LIMIT ? OFFSET ?",
        [MATCH_START, MATCH_END, *parameters, limit, offset],
    )
    items = [
        DocumentHit(
            doc_id=row["doc_id"],
            course_id=course_id,
            page=row["page"],
            chunk=row["chunk"],
            snippet=snippet_parts(highlighted=row["highlighted"]),
        )
        for row in rows
    ]
    return DocumentSearchPage(items=items, total=total)

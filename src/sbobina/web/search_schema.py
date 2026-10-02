"""Schema, connection and row types of the derived search index."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sbobina.search_text import SnippetPart
from sbobina.web.errors import AppError

SCHEMA_VERSION = 1
Variant = Literal["original", "corrected"]
CORRUPTION_CODES = {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}
PRIMARY_ERROR_MASK = 0xFF


class SearchUnavailableError(AppError):
    """The SQLite runtime cannot provide full-text search."""


class SearchCorruptError(AppError):
    """Corrupt derived data was discarded; reconcile from source files again."""


class SchemaMismatchError(Exception):
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


@dataclass(frozen=True)
class LectureHit:
    job_id: str
    passage_count: int


@dataclass(frozen=True)
class LecturePage:
    items: list[LectureHit]
    total: int


def create_schema(connection: sqlite3.Connection) -> None:
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


def connect_index(path: Path) -> sqlite3.Connection:
    is_existing = path.exists()
    connection = sqlite3.connect(database=path)
    connection.row_factory = sqlite3.Row
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if is_existing and version != SCHEMA_VERSION:
            raise SchemaMismatchError(
                f"Schema version {version}, expected {SCHEMA_VERSION}"
            )
        with connection:
            create_schema(connection=connection)
    except Exception:
        connection.close()
        raise
    return connection

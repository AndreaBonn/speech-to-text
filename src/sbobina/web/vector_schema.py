"""SQLite schema, file locks and corruption recovery for the vector store."""

import sqlite3
import sys
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from filelock import FileLock

if sys.platform != "win32":
    import fcntl

SCHEMA_VERSION = 1
BUSY_TIMEOUT_PRAGMA = "PRAGMA busy_timeout = 5000"
CORRUPTION_CODES = {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}
PRIMARY_ERROR_MASK = 0xFF
SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE models (
    model_key TEXT PRIMARY KEY, dimensions INTEGER NOT NULL CHECK(dimensions > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE units (
    course TEXT NOT NULL, unit_id TEXT NOT NULL, text_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(course, unit_id)
);
CREATE INDEX idx_units_text_sha256 ON units(text_sha256);
CREATE TABLE vectors (
    model_key TEXT NOT NULL REFERENCES models(model_key), text_sha256 TEXT NOT NULL,
    vector BLOB NOT NULL, truncated INTEGER NOT NULL CHECK(truncated IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(model_key, text_sha256)
);
PRAGMA user_version = 1;
COMMIT;
"""


class SchemaMismatchError(Exception):
    pass


class IntegrityError(sqlite3.DatabaseError):
    sqlite_errorcode = sqlite3.SQLITE_CORRUPT


@contextmanager
def file_lock(path: Path, *, is_exclusive: bool) -> Iterator[None]:
    if sys.platform == "win32":
        # No flock on Windows and msvcrt locks have no shared mode: readers
        # serialize with each other too, which costs concurrency, not safety.
        with FileLock(path.with_suffix(".lock")):
            yield
        return
    with path.with_suffix(".lock").open(mode="a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX if is_exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    with closing(sqlite3.connect(database=path)) as connection:
        connection.execute(BUSY_TIMEOUT_PRAGMA)
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection


def check_schema(path: Path, *, rebuild_needed: bool = False) -> None:
    is_existing = path.exists()
    with connect(path=path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if is_existing and version != SCHEMA_VERSION:
            raise SchemaMismatchError(
                f"Schema version {version}, expected {SCHEMA_VERSION}"
            )
        connection.execute("PRAGMA journal_mode = WAL")
        if not is_existing:
            connection.executescript(SCHEMA)
        elif connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise IntegrityError("Vector database integrity check failed")
        with connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS store_states ("
                "id INTEGER PRIMARY KEY CHECK(id = 1), "
                "rebuild_needed INTEGER NOT NULL CHECK(rebuild_needed IN (0, 1)))"
            )
            connection.execute(
                "INSERT OR IGNORE INTO store_states (id, rebuild_needed) VALUES (1, ?)",
                (rebuild_needed,),
            )


def backup_database(path: Path) -> None:
    backup = path.with_suffix(".bak")
    path.replace(target=backup)
    # Preserve any uncheckpointed pages together with their original database.
    for suffix in ("-wal", "-shm"):
        source = Path(str(path) + suffix)
        destination = Path(str(backup) + suffix)
        destination.unlink(missing_ok=True)
        if source.exists():
            source.replace(target=destination)

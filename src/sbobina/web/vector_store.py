"""Independent float32 cache; Unix file locks coordinate recovery across processes."""

import fcntl
import json
import logging
import sqlite3
import struct
from collections.abc import Collection, Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

__all__ = ["Coverage", "StoredVector", "VectorStore"]

SCHEMA_VERSION = 1
BUSY_TIMEOUT_PRAGMA = "PRAGMA busy_timeout = 5000"
CORRUPTION_CODES = {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}
PRIMARY_ERROR_MASK = 0xFF
FLOAT32_SIZE = 4
logger = logging.getLogger(__name__)
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


@dataclass(frozen=True)
class StoredVector:
    """One caller-hashed vector, encoded as little-endian float32 on disk."""

    text_sha256: str
    vector: tuple[float, ...]
    truncated: bool


@dataclass(frozen=True)
class Coverage:
    """Counts of units, including duplicate hashes, for one model and course."""

    embedded: int
    total: int
    truncated: int


class _SchemaMismatchError(Exception):
    pass


class _IntegrityError(sqlite3.DatabaseError):
    sqlite_errorcode = sqlite3.SQLITE_CORRUPT


@contextmanager
def _file_lock(path: Path, *, is_exclusive: bool) -> Iterator[None]:
    with path.with_suffix(".lock").open(mode="a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX if is_exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


@contextmanager
def _connect(path: Path) -> Iterator[sqlite3.Connection]:
    with closing(sqlite3.connect(database=path)) as connection:
        connection.execute(BUSY_TIMEOUT_PRAGMA)
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection


def _check_schema(path: Path) -> None:
    is_existing = path.exists()
    with _connect(path=path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if is_existing and version != SCHEMA_VERSION:
            raise _SchemaMismatchError(
                f"Schema version {version}, expected {SCHEMA_VERSION}"
            )
        connection.execute("PRAGMA journal_mode = WAL")
        if not is_existing:
            connection.executescript(SCHEMA)
        elif connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise _IntegrityError("Vector database integrity check failed")


def _backup_database(path: Path) -> None:
    backup = path.with_suffix(".bak")
    path.replace(target=backup)
    # Preserve any uncheckpointed pages together with their original database.
    for suffix in ("-wal", "-shm"):
        source = Path(str(path) + suffix)
        destination = Path(str(backup) + suffix)
        destination.unlink(missing_ok=True)
        if source.exists():
            source.replace(target=destination)


def _encode_vectors(vectors: Sequence[StoredVector]) -> list[tuple[str, bytes, bool]]:
    dimensions = len(vectors[0].vector)
    if not dimensions or any(len(item.vector) != dimensions for item in vectors):
        raise ValueError("Inconsistent or empty vector dimensions")
    return [
        (item.text_sha256, struct.pack(f"<{dimensions}f", *item.vector), item.truncated)
        for item in vectors
    ]


class VectorStore:
    """Thread-safe cache at an explicit path (normally data/vectors.sqlite3).

    Each operation owns its connection. All store instances cooperate through
    a shared file lock; initialization/recovery takes the exclusive lock.
    ``rebuild_needed`` reports recovery performed by this instance at opening.
    Model keys and hashes are opaque values supplied by the caller.

    Construct one instance per process, once at module scope or as an injected
    singleton, and reuse it across requests/questions. Never recreate it per
    request: initialization runs ``quick_check`` on an existing compatible
    database, with a cost proportional to the database size.
    ``sync_units`` and ``coverage`` require keyword arguments, unlike the older
    methods that also accept positional arguments.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._version_lock = Lock()
        self._observer: sqlite3.Connection | None = None
        self._version_state: tuple[int, int, int] | None = None
        self._revision = 0
        self.rebuild_needed = False
        path.parent.mkdir(parents=True, exist_ok=True)
        with _file_lock(path=path, is_exclusive=True):
            try:
                _check_schema(path=path)
            except (_SchemaMismatchError, sqlite3.DatabaseError) as error:
                if (
                    isinstance(error, sqlite3.DatabaseError)
                    and error.sqlite_errorcode & PRIMARY_ERROR_MASK
                    not in CORRUPTION_CODES
                ):
                    raise
                _backup_database(path=path)
                logger.warning("Vector store rebuild needed: %s (%s)", path, error)
                _check_schema(path=path)
                self.rebuild_needed = True

    def data_version(self) -> int:
        """Return a local cache stamp tracking PRAGMA data_version and replacement."""
        with self._version_lock, _file_lock(path=self._path, is_exclusive=False):
            stat = self._path.stat()
            identity = (stat.st_dev, stat.st_ino)
            if self._version_state is None or self._version_state[:2] != identity:
                if self._observer is not None:
                    self._observer.close()
                self._observer = sqlite3.connect(
                    database=self._path.resolve().as_uri() + "?mode=ro",
                    uri=True,
                    check_same_thread=False,
                )
            assert self._observer is not None
            version = int(self._observer.execute("PRAGMA data_version").fetchone()[0])
            state = (*identity, version)
            if state != self._version_state:
                self._revision += 1
                self._version_state = state
            return self._revision

    def close(self) -> None:
        """Release the observer; a later version read opens a fresh observer."""
        with self._version_lock:
            if self._observer is not None:
                self._observer.close()
                self._observer = None
            self._version_state = None

    @contextmanager
    def _session(self, *, is_write: bool = False) -> Iterator[sqlite3.Connection]:
        with (
            _file_lock(path=self._path, is_exclusive=False),
            _connect(path=self._path) as connection,
            connection,
        ):
            if is_write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection

    def missing_hashes(self, model_key: str, hashes: Collection[str]) -> set[str]:
        """Return distinct requested hashes absent from this model's cache."""
        with self._session() as connection:
            rows = connection.execute(
                "SELECT requested.value FROM json_each(?) AS requested "
                "LEFT JOIN vectors ON vectors.text_sha256 = requested.value "
                "AND vectors.model_key = ? WHERE vectors.text_sha256 IS NULL",
                (json.dumps(list(hashes)), model_key),
            )
            return {row[0] for row in rows}

    def put_vectors(self, model_key: str, vectors: Sequence[StoredVector]) -> None:
        """Atomically upsert one batch; reject inconsistent dimensions per model."""
        if not vectors:
            return
        encoded = _encode_vectors(vectors=vectors)
        dimensions = len(vectors[0].vector)
        with self._session(is_write=True) as connection:
            connection.execute(
                "INSERT INTO models (model_key, dimensions) VALUES (?, ?) "
                "ON CONFLICT(model_key) DO NOTHING",
                (model_key, dimensions),
            )
            existing = connection.execute(
                "SELECT dimensions FROM models WHERE model_key = ?",
                (model_key,),
            ).fetchone()[0]
            if existing != dimensions:
                raise ValueError("Vector dimensions differ from the registered model")
            connection.executemany(
                "INSERT INTO vectors (model_key, text_sha256, vector, truncated) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(model_key, text_sha256) DO UPDATE SET "
                "vector = excluded.vector, truncated = excluded.truncated, "
                "updated_at = CURRENT_TIMESTAMP",
                [(model_key, *row) for row in encoded],
            )

    def vectors_for_units(
        self, model_key: str, units: Mapping[str, str]
    ) -> dict[str, StoredVector]:
        """Return cached vectors keyed by supplied unit ID; omit missing hashes."""
        with self._session() as connection:
            rows = connection.execute(
                "SELECT requested.key, vectors.text_sha256, vector, truncated "
                "FROM json_each(?) AS requested JOIN vectors "
                "ON vectors.text_sha256 = requested.value AND vectors.model_key = ?",
                (json.dumps(dict(units)), model_key),
            )
            return {
                unit_id: StoredVector(
                    text_sha256=text_hash,
                    vector=struct.unpack(f"<{len(blob) // FLOAT32_SIZE}f", blob),
                    truncated=bool(truncated),
                )
                for unit_id, text_hash, blob, truncated in rows
            }

    def sync_units(self, *, course: str, units: Mapping[str, str]) -> None:
        """Atomically replace the entire unit_id -> text_sha256 course manifest.

        Other courses and cached vectors remain intact.
        """
        with self._session(is_write=True) as connection:
            connection.execute("DELETE FROM units WHERE course = ?", (course,))
            connection.executemany(
                "INSERT INTO units (course, unit_id, text_sha256) VALUES (?, ?, ?)",
                [(course, unit_id, text_hash) for unit_id, text_hash in units.items()],
            )

    def coverage(self, *, course: str, model_key: str) -> Coverage:
        """Read coverage of the previously synchronized manifest without writes.

        Duplicate hashes count once per unit, not once per cached vector.
        Courses without a synchronized manifest have zero counts.
        """
        with self._session() as connection:
            embedded, total, truncated = connection.execute(
                "SELECT count(vectors.text_sha256), count(*), coalesce(sum(truncated), 0) "
                "FROM units LEFT JOIN vectors ON vectors.text_sha256 = units.text_sha256 "
                "AND vectors.model_key = ? WHERE units.course = ?",
                (model_key, course),
            ).fetchone()
            return Coverage(embedded=embedded, total=total, truncated=truncated)

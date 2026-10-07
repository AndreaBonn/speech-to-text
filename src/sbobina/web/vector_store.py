"""Independent float32 cache; Unix file locks coordinate recovery across processes."""

import json
import logging
import sqlite3
import struct
from collections.abc import Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from sbobina.web.vector_schema import (
    CORRUPTION_CODES,
    PRIMARY_ERROR_MASK,
    SchemaMismatchError,
    backup_database,
    check_schema,
    connect,
    file_lock,
)

__all__ = ["Coverage", "StoredVector", "VectorStore"]

FLOAT32_SIZE = 4
logger = logging.getLogger(__name__)


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
    ``rebuild_needed`` reports a recovery not yet followed by a reindex; this
    instance's recovery sets it at opening, ``data_version()`` refreshes it from
    the marker persisted by any instance.
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
        with file_lock(path=path, is_exclusive=True):
            try:
                check_schema(path=path)
            except (SchemaMismatchError, sqlite3.DatabaseError) as error:
                if (
                    isinstance(error, sqlite3.DatabaseError)
                    and error.sqlite_errorcode & PRIMARY_ERROR_MASK
                    not in CORRUPTION_CODES
                ):
                    raise
                backup_database(path=path)
                logger.warning("Vector store rebuild needed: %s (%s)", path, error)
                check_schema(path=path, rebuild_needed=True)
                self.rebuild_needed = True

    def data_version(self) -> int:
        """Return a local cache stamp tracking PRAGMA data_version and replacement."""
        with self._version_lock, file_lock(path=self._path, is_exclusive=False):
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
            state = (
                *identity,
                self._observer.execute("PRAGMA data_version").fetchone()[0],
            )
            if state != self._version_state:
                self.rebuild_needed = bool(
                    self._observer.execute(
                        "SELECT rebuild_needed FROM store_states WHERE id = 1"
                    ).fetchone()[0]
                )
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
            file_lock(path=self._path, is_exclusive=False),
            connect(path=self._path) as connection,
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
                "SELECT dimensions FROM models WHERE model_key = ?", (model_key,)
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

        Other courses and cached vectors remain intact; the persisted rebuild
        marker is cleared in the same transaction.
        """
        with self._session(is_write=True) as connection:
            connection.execute("DELETE FROM units WHERE course = ?", (course,))
            connection.executemany(
                "INSERT INTO units (course, unit_id, text_sha256) VALUES (?, ?, ?)",
                [(course, unit_id, text_hash) for unit_id, text_hash in units.items()],
            )
            connection.execute("UPDATE store_states SET rebuild_needed = 0")

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

    def has_other_models(self, *, model_key: str) -> bool:
        """Report registered model identities different from the configured one."""
        with self._session() as connection:
            return bool(
                connection.execute(
                    "SELECT EXISTS(SELECT 1 FROM models WHERE model_key != ?)",
                    (model_key,),
                ).fetchone()[0]
            )

    def purge_obsolete_models(self, *, model_key: str) -> int:
        """Delete old models only when all nonempty manifests are covered; vacuum."""
        with (
            file_lock(path=self._path, is_exclusive=True),
            connect(path=self._path) as connection,
        ):
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                total, embedded = connection.execute(
                    "SELECT count(*), count(vectors.text_sha256) FROM units "
                    "LEFT JOIN vectors ON units.text_sha256 = vectors.text_sha256 "
                    "AND vectors.model_key = ?",
                    (model_key,),
                ).fetchone()
                if not total or embedded != total:
                    return 0
                removed = connection.execute(
                    "DELETE FROM vectors WHERE model_key != ?", (model_key,)
                ).rowcount
                connection.execute(
                    "DELETE FROM models WHERE model_key != ?", (model_key,)
                )
            if removed:
                connection.execute("VACUUM")
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return removed

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from sbobina.web.vector_store import StoredVector, VectorStore


def test_data_version_stays_stable_on_reads_and_changes_after_local_write(
    tmp_path: Path,
) -> None:
    store = VectorStore(path=tmp_path / "vectors.sqlite3")
    initial = store.data_version()
    assert store.data_version() == initial
    store.sync_units(course="course", units={"unit": "hash"})
    updated = store.data_version()
    assert updated != initial
    assert store.data_version() == updated
    store.coverage(course="course", model_key="model")
    assert store.data_version() == updated
    store.close()


def test_data_version_detects_other_instance_and_external_connection_writes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "vectors.sqlite3"
    store = VectorStore(path=path)
    other = VectorStore(path=path)
    initial = store.data_version()
    other.put_vectors(
        model_key="model",
        vectors=[StoredVector(text_sha256="hash", vector=(1.0,), truncated=False)],
    )
    updated = store.data_version()
    assert updated != initial
    with closing(sqlite3.connect(database=path)) as connection, connection:
        connection.execute("INSERT INTO units(course, unit_id, text_sha256) VALUES ('c', 'u', 'h')")
    assert store.data_version() != updated
    store.close()
    other.close()


def test_data_version_detects_recovery_and_reads_replacement_database(
    tmp_path: Path,
) -> None:
    path = tmp_path / "vectors.sqlite3"
    store = VectorStore(path=path)
    initial = store.data_version()
    with closing(sqlite3.connect(database=path)) as connection:
        connection.execute("PRAGMA user_version = 999")
    rebuilt = VectorStore(path=path)
    assert rebuilt.rebuild_needed
    rebuilt.data_version()
    rebuilt.sync_units(course="course", units={"new": "hash"})
    assert store.data_version() != initial
    assert store.coverage(course="course", model_key="model").total == 1
    store.close()
    rebuilt.close()


def test_data_version_supports_threads_and_close_invalidates_previous_stamp(
    tmp_path: Path,
) -> None:
    store = VectorStore(path=tmp_path / "vectors.sqlite3")
    initial = store.data_version()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda _: store.data_version(), range(4))) == [initial] * 4
    store.close()
    store.close()
    assert store.data_version() != initial
    store.close()

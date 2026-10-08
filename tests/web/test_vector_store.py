import sqlite3
import struct
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier

import pytest

from sbobina.embedding_prompts import EMBEDDING_PROMPT_VERSION
from sbobina.embedding_units import content_hash
from sbobina.web.search_index import open_index
from sbobina.web.vector_store import Coverage, StoredVector, VectorStore

DIMENSIONS = 4096
FLOAT32_BYTES = 16384
OPERATIONS = 200
MODEL = f"qwen3-embedding:8b:digest:2048:prompt-{EMBEDDING_PROMPT_VERSION}"
OTHER_MODEL = "another-model:digest:2048:prompt-1"
HASH = content_hash(text="one passage")
OTHER_HASH = content_hash(text="another passage")
VALUES = tuple(index / 8 for index in range(DIMENSIONS))
VECTOR = StoredVector(text_sha256=HASH, vector=VALUES, truncated=True)
MANIFEST = {"passage-a": HASH, "passage-b": HASH, "passage-c": OTHER_HASH}


def test_put_vectors_float32_round_trip_preserves_bytes_and_flags(
    tmp_path: Path,
) -> None:
    path = tmp_path / "data" / "vectors.sqlite3"
    store = VectorStore(path=path)
    store.put_vectors(model_key=MODEL, vectors=[VECTOR])
    reopened = VectorStore(path=path)
    assert reopened.vectors_for_units(model_key=MODEL, units=MANIFEST) == {
        "passage-a": VECTOR,
        "passage-b": VECTOR,
    }
    with closing(sqlite3.connect(database=path)) as connection:
        blob, truncated = connection.execute(
            "SELECT vector, truncated FROM vectors"
        ).fetchone()
        assert len(blob) == FLOAT32_BYTES
        assert blob == struct.pack(f"<{DIMENSIONS}f", *VALUES)
        assert truncated == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert reopened.rebuild_needed is False


def test_missing_hashes_models_are_isolated_and_cached_by_hash(tmp_path: Path) -> None:
    store = VectorStore(path=tmp_path / "vectors.sqlite3")
    hashes = [HASH, HASH, OTHER_HASH]
    assert store.missing_hashes(model_key=MODEL, hashes=hashes) == {HASH, OTHER_HASH}
    store.put_vectors(model_key=MODEL, vectors=[VECTOR])
    assert store.missing_hashes(model_key=MODEL, hashes=hashes) == {OTHER_HASH}
    assert store.missing_hashes(model_key=OTHER_MODEL, hashes=hashes) == {
        HASH,
        OTHER_HASH,
    }
    alternative = StoredVector(text_sha256=HASH, vector=(1.0, 2.0), truncated=False)
    store.put_vectors(model_key=OTHER_MODEL, vectors=[alternative])
    assert store.vectors_for_units(model_key=OTHER_MODEL, units={"a": HASH}) == {
        "a": alternative
    }
    assert store.vectors_for_units(model_key=MODEL, units={"a": HASH}) == {"a": VECTOR}


def test_coverage_manifest_counts_units_truncated_and_isolates_models(
    tmp_path: Path,
) -> None:
    store = VectorStore(path=tmp_path / "vectors.sqlite3")
    store.sync_units(course="course", units=MANIFEST)
    assert store.coverage(course="course", model_key=MODEL) == Coverage(
        embedded=0, total=3, truncated=0
    )
    store.put_vectors(model_key=MODEL, vectors=[VECTOR])
    store.sync_units(course="course", units=MANIFEST)
    assert store.coverage(course="course", model_key=MODEL) == Coverage(
        embedded=2, total=3, truncated=2
    )
    store.sync_units(course="second", units=MANIFEST)
    assert store.coverage(course="second", model_key=MODEL) == Coverage(
        embedded=2, total=3, truncated=2
    )
    store.sync_units(course="course", units=MANIFEST)
    assert store.coverage(course="course", model_key=OTHER_MODEL) == Coverage(
        embedded=0, total=3, truncated=0
    )


def test_sync_units_removed_unit_is_excluded_from_coverage(tmp_path: Path) -> None:
    store = VectorStore(path=tmp_path / "vectors.sqlite3")
    store.put_vectors(model_key=MODEL, vectors=[VECTOR])
    store.sync_units(course="course", units=MANIFEST)
    store.sync_units(course="second", units=MANIFEST)
    store.sync_units(course="course", units={"a": OTHER_HASH})
    assert store.coverage(course="course", model_key=MODEL) == Coverage(
        embedded=0, total=1, truncated=0
    )
    with closing(sqlite3.connect(database=tmp_path / "vectors.sqlite3")) as connection:
        assert connection.execute(
            "SELECT course, count(*) FROM units GROUP BY course ORDER BY course"
        ).fetchall() == [("course", 1), ("second", 3)]


def test_coverage_unsynchronized_course_returns_zero_counts(tmp_path: Path) -> None:
    store = VectorStore(path=tmp_path / "vectors.sqlite3")
    assert store.coverage(course="unseen", model_key=MODEL) == Coverage(
        embedded=0, total=0, truncated=0
    )


def test_coverage_read_preserves_external_data_version(tmp_path: Path) -> None:
    path = tmp_path / "vectors.sqlite3"
    store = VectorStore(path=path)
    store.put_vectors(model_key=MODEL, vectors=[VECTOR])
    with closing(sqlite3.connect(database=path)) as observer:
        initial = observer.execute("PRAGMA data_version").fetchone()[0]
        store.sync_units(course="course", units=MANIFEST)
        before = observer.execute("PRAGMA data_version").fetchone()[0]
        assert before != initial
        assert store.coverage(course="course", model_key=MODEL) == Coverage(
            embedded=2, total=3, truncated=2
        )
        assert observer.execute("PRAGMA data_version").fetchone()[0] == before


def test_put_vectors_upsert_and_empty_inputs_preserve_cache(tmp_path: Path) -> None:
    store = VectorStore(path=tmp_path / "vectors.sqlite3")
    store.put_vectors(model_key=MODEL, vectors=[VECTOR])
    replacement = StoredVector(
        text_sha256=HASH, vector=tuple(-v for v in VALUES), truncated=False
    )
    store.put_vectors(model_key=MODEL, vectors=[replacement])
    store.put_vectors(model_key=MODEL, vectors=[])
    assert store.vectors_for_units(model_key=MODEL, units={"a": HASH}) == {
        "a": replacement
    }
    assert store.missing_hashes(model_key=MODEL, hashes=[]) == set()
    assert store.vectors_for_units(model_key=MODEL, units={}) == {}
    store.sync_units(course="c", units={"a": HASH})
    assert store.coverage(course="c", model_key=MODEL) == Coverage(
        embedded=1, total=1, truncated=0
    )
    store.sync_units(course="c", units={})
    assert store.coverage(course="c", model_key=MODEL) == Coverage(
        embedded=0, total=0, truncated=0
    )


def test_put_vectors_inconsistent_dimensions_rolls_back_entire_batch(
    tmp_path: Path,
) -> None:
    path = tmp_path / "vectors.sqlite3"
    store = VectorStore(path=path)
    invalid = StoredVector(text_sha256=OTHER_HASH, vector=(1.0,), truncated=False)
    with pytest.raises(ValueError, match="dimension"):
        store.put_vectors(model_key=MODEL, vectors=[VECTOR, invalid])
    assert store.missing_hashes(model_key=MODEL, hashes=[HASH, OTHER_HASH]) == {
        HASH,
        OTHER_HASH,
    }
    store.put_vectors(model_key=MODEL, vectors=[VECTOR])
    with pytest.raises(ValueError, match="dimension"):
        store.put_vectors(model_key=MODEL, vectors=[invalid])
    assert store.vectors_for_units(model_key=MODEL, units={"a": HASH}) == {"a": VECTOR}


def test_put_vectors_sql_failure_rolls_back_previous_rows(tmp_path: Path) -> None:
    path = tmp_path / "vectors.sqlite3"
    store = VectorStore(path=path)
    with closing(sqlite3.connect(database=path)) as connection:
        connection.execute(
            "CREATE TRIGGER reject_second BEFORE INSERT ON vectors WHEN (SELECT count(*) FROM vectors) = 1 BEGIN SELECT RAISE(ABORT, 'batch rejected'); END"
        )
    second = StoredVector(text_sha256=OTHER_HASH, vector=VALUES, truncated=False)
    with pytest.raises(sqlite3.IntegrityError, match="batch rejected"):
        store.put_vectors(model_key=MODEL, vectors=[VECTOR, second])
    assert store.missing_hashes(model_key=MODEL, hashes=[HASH, OTHER_HASH]) == {
        HASH,
        OTHER_HASH,
    }
    store.put_vectors(model_key=MODEL, vectors=[VECTOR])
    assert store.missing_hashes(model_key=MODEL, hashes=[HASH, OTHER_HASH]) == {
        OTHER_HASH
    }


def _exercise_store(path: Path, barrier: Barrier, is_writer: bool) -> int:
    barrier.wait(timeout=10)
    store = VectorStore(path=path)
    for operation in range(OPERATIONS):
        barrier.wait(timeout=10)
        text_hash = content_hash(text=str(operation))
        vector = StoredVector(text_sha256=text_hash, vector=VALUES, truncated=False)
        if is_writer:
            store.put_vectors(model_key=MODEL, vectors=[vector])
        else:
            found = store.vectors_for_units(model_key=MODEL, units={"a": text_hash})
            assert found in ({}, {"a": vector})
    return OPERATIONS


def test_vector_store_reader_writer_threads_complete_200_operations(
    tmp_path: Path,
) -> None:
    path = tmp_path / "vectors.sqlite3"
    barrier = Barrier(parties=2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_exercise_store, path=path, barrier=barrier, is_writer=role)
            for role in (True, False)
        ]
        assert [future.result(timeout=30) for future in futures] == [
            OPERATIONS,
            OPERATIONS,
        ]
    store = VectorStore(path=path)
    units = {str(i): content_hash(text=str(i)) for i in range(OPERATIONS)}
    store.sync_units(course="c", units=units)
    assert store.coverage(course="c", model_key=MODEL) == Coverage(
        embedded=OPERATIONS, total=OPERATIONS, truncated=0
    )


def test_vector_store_search_index_rebuild_keeps_vectors(tmp_path: Path) -> None:
    path = tmp_path / "vectors.sqlite3"
    VectorStore(path=path).put_vectors(model_key=MODEL, vectors=[VECTOR])
    search_path = tmp_path / "search.sqlite3"
    search_path.write_bytes(bytes(range(256)) * 16)

    with closing(open_index(path=search_path)) as index:
        rebuilt_total = index.search(
            match='"causa"', job_ids=None, limit=1, offset=0
        ).total

    assert rebuilt_total == 0
    assert VectorStore(path=path).vectors_for_units(
        model_key=MODEL, units={"a": HASH}
    ) == {"a": VECTOR}


def test_coverage_sql_metacharacters_are_bound_as_values(tmp_path: Path) -> None:
    store = VectorStore(path=tmp_path / "vectors.sqlite3")
    malicious = "x'); DROP TABLE vectors; --"
    vector = StoredVector(text_sha256=malicious, vector=(1.0,), truncated=False)
    store.put_vectors(model_key=malicious, vectors=[vector])
    store.sync_units(course=malicious, units={malicious: malicious})
    assert store.coverage(course=malicious, model_key=malicious) == Coverage(
        embedded=1, total=1, truncated=0
    )
    assert store.vectors_for_units(
        model_key=malicious, units={malicious: malicious}
    ) == {malicious: vector}

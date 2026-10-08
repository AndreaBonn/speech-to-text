import logging
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from sbobina.embedding_prompts import EMBEDDING_PROMPT_VERSION
from sbobina.embedding_units import content_hash
from sbobina.web.vector_schema import IntegrityError, check_schema
from sbobina.web.vector_store import StoredVector, VectorStore

MODEL = f"qwen3-embedding:8b:digest:2048:prompt-{EMBEDDING_PROMPT_VERSION}"
HASH = content_hash(text="one passage")
VECTOR = StoredVector(
    text_sha256=HASH, vector=tuple(index / 8 for index in range(4096)), truncated=True
)


def test_check_schema_corrupted_data_page_raises_integrity_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "vectors.sqlite3"
    check_schema(path=path)
    with closing(sqlite3.connect(database=path)) as connection:
        connection.execute(
            "INSERT INTO models (model_key, dimensions, created_at, updated_at) "
            "VALUES ('probe', 42, '', '')"
        )
        connection.commit()
        page = connection.execute(
            "SELECT rootpage FROM sqlite_master WHERE name = 'models'"
        ).fetchone()[0]
        size = connection.execute("PRAGMA page_size").fetchone()[0]
        assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]

    # The single row ends with the one-byte dimension; empty timestamps add no bytes.
    with path.open(mode="r+b") as stream:
        stream.seek(page * size - 1)
        assert stream.read(1) == b"\x2a"
        stream.seek(page * size - 1)
        stream.write(b"\x00")
    with closing(sqlite3.connect(database=path)) as connection:
        assert connection.execute("PRAGMA quick_check").fetchall() == [
            ("CHECK constraint failed in models",)
        ]

    with pytest.raises(IntegrityError, match="Vector database integrity check failed"):
        check_schema(path=path)


@pytest.mark.parametrize("version", [0, 999])
def test_vector_store_schema_mismatch_preserves_backup_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, version: int
) -> None:
    path = tmp_path / "vectors.sqlite3"
    VectorStore(path=path).put_vectors(model_key=MODEL, vectors=[VECTOR])
    path.with_suffix(".bak").write_bytes(b"previous backup")
    with closing(sqlite3.connect(database=path)) as connection:
        connection.execute(
            "PRAGMA user_version = 0" if version == 0 else "PRAGMA user_version = 999"
        )
    with caplog.at_level(logging.WARNING):
        store = VectorStore(path=path)
    assert store.rebuild_needed is True
    assert store.missing_hashes(model_key=MODEL, hashes=[HASH]) == {HASH}
    with closing(sqlite3.connect(database=path.with_suffix(".bak"))) as backup:
        assert backup.execute("SELECT count(*) FROM vectors").fetchone()[0] == 1
    with closing(sqlite3.connect(database=path)) as connection:
        assert connection.execute(
            "SELECT (SELECT count(*) FROM models), (SELECT count(*) FROM units), (SELECT count(*) FROM vectors)"
        ).fetchone() == (0, 0, 0)
    assert any(
        record.levelno == logging.WARNING and "rebuild" in record.message
        for record in caplog.records
    )


@pytest.mark.parametrize("is_page_corrupt", [False, True])
def test_vector_store_corruption_preserves_original_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, is_page_corrupt: bool
) -> None:
    path = tmp_path / "vectors.sqlite3"
    corrupt = b"this is not a SQLite database" * 100
    if is_page_corrupt:
        VectorStore(path=path).put_vectors(model_key=MODEL, vectors=[VECTOR])
        with closing(sqlite3.connect(database=path)) as connection:
            page = connection.execute(
                "SELECT rootpage FROM sqlite_master WHERE name = 'vectors'"
            ).fetchone()[0]
            size = connection.execute("PRAGMA page_size").fetchone()[0]
        data = bytearray(path.read_bytes())
        data[(page - 1) * size] = 0
        corrupt = bytes(data)
    path.write_bytes(corrupt)
    with caplog.at_level(logging.WARNING):
        store = VectorStore(path=path)
    assert path.with_suffix(".bak").read_bytes() == corrupt
    assert store.rebuild_needed is True
    assert store.missing_hashes(model_key=MODEL, hashes=[HASH]) == {HASH}
    store.put_vectors(model_key=MODEL, vectors=[VECTOR])
    assert store.missing_hashes(model_key=MODEL, hashes=[HASH]) == set()
    assert any(record.levelno == logging.WARNING for record in caplog.records)


def test_vector_store_unrelated_database_error_preserves_file(tmp_path: Path) -> None:
    path = tmp_path / "vectors.sqlite3"
    VectorStore(path=path).put_vectors(model_key=MODEL, vectors=[VECTOR])
    with closing(sqlite3.connect(database=path)) as connection:
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("BEGIN EXCLUSIVE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            VectorStore(path=path)
        connection.rollback()
    assert path.exists()
    assert not path.with_suffix(".bak").exists()
    assert VectorStore(path=path).vectors_for_units(
        model_key=MODEL, units={"a": HASH}
    ) == {"a": VECTOR}

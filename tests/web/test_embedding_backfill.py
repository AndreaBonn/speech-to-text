import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest
from vector_reconcile_fixtures import (
    FakeEmbedder,
    make_context,
    write_course,
    write_pages,
)

from sbobina.ollama_embed import ModelStatus
from sbobina.settings import settings
from sbobina.web.embedding_backfill import enqueue_backfill
from sbobina.web.embedding_store import (
    EmbeddingStatus,
    create_embed,
    load_embed,
    save_embed,
)
from sbobina.web.job_store import JobStore
from sbobina.web.vector_reconcile import embed_course, embedding_model_key
from sbobina.web.vector_store import Coverage, StoredVector, VectorStore

STATUS = ModelStatus(digest="backfill-test", dimensions=2)
MODEL_KEY = embedding_model_key(model=settings.embedding_model, status=STATUS)
OLD_MODEL = "previous-model"
LARGE_DIMENSIONS = 4096
VECTOR_COUNT = 128


def test_enqueue_backfill_three_courses_queues_only_two_incomplete(
    tmp_path: Path,
) -> None:
    store = JobStore(data_dir=tmp_path)
    vectors = VectorStore(path=tmp_path / "vectors.sqlite3")
    courses = [
        write_course(store=store, label=label) for label in ("Uno", "Due", "Tre")
    ]
    for course in courses:
        vectors.sync_units(course=course.key, units={"unit": course.key})
    vectors.put_vectors(
        model_key=MODEL_KEY,
        vectors=[StoredVector(text_sha256="uno", vector=(1.0, 0.0), truncated=False)],
    )
    version = vectors.data_version()

    result = enqueue_backfill(store=store, vectors=vectors, status=STATUS)

    assert result.model_change_pending is False
    assert {item.course_id for item in result.items} == {c.id for c in courses[1:]}
    assert all(item.action == "embed" for item in result.items)
    assert load_embed(course_dir=store.courses_dir / courses[0].id) is None
    for course in courses[1:]:
        record = load_embed(course_dir=store.courses_dir / course.id)
        assert record is not None and record.status is EmbeddingStatus.QUEUED
    assert vectors.data_version() == version
    vectors.close()


def test_enqueue_backfill_model_change_requires_confirmation(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    vectors = VectorStore(path=tmp_path / "vectors.sqlite3")
    course = write_course(store=store)
    vectors.sync_units(course=course.key, units={"unit": "hash"})
    vectors.put_vectors(
        model_key=OLD_MODEL,
        vectors=[StoredVector(text_sha256="hash", vector=(1.0, 0.0), truncated=False)],
    )

    blocked = enqueue_backfill(store=store, vectors=vectors, status=STATUS)

    assert blocked.model_change_pending is True
    assert blocked.items == ()
    assert load_embed(course_dir=store.courses_dir / course.id) is None
    accepted = enqueue_backfill(
        store=store, vectors=vectors, status=STATUS, confirm_model_change=True
    )
    assert accepted.model_change_pending is False
    assert [item.course_id for item in accepted.items] == [course.id]
    assert vectors.coverage(course=course.key, model_key=OLD_MODEL).embedded == 1


def test_enqueue_backfill_empty_manifest_does_not_enqueue(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    vectors = VectorStore(path=tmp_path / "vectors.sqlite3")
    course = write_course(store=store)
    result = enqueue_backfill(store=store, vectors=vectors, status=STATUS)
    assert result.items == ()
    assert result.model_change_pending is False
    assert vectors.coverage(course=course.key, model_key=MODEL_KEY) == Coverage(
        embedded=0, total=0, truncated=0
    )


@pytest.mark.parametrize(
    "existing_status", [EmbeddingStatus.QUEUED, EmbeddingStatus.RUNNING]
)
def test_enqueue_backfill_active_course_does_not_block_remaining_courses(
    tmp_path: Path, existing_status: EmbeddingStatus
) -> None:
    store = JobStore(data_dir=tmp_path)
    vectors = VectorStore(path=tmp_path / "vectors.sqlite3")
    active = write_course(store=store, label="Attivo")
    pending = write_course(store=store, label="Incompleto")
    for course in (active, pending):
        vectors.sync_units(course=course.key, units={"unit": course.key})
    directory = store.courses_dir / active.id
    record = replace(create_embed(course_dir=directory), status=existing_status)
    save_embed(course_dir=directory, record=record)

    result = enqueue_backfill(store=store, vectors=vectors, status=STATUS)

    assert [item.course_id for item in result.items] == [pending.id]
    assert load_embed(course_dir=directory) == record
    assert enqueue_backfill(store=store, vectors=vectors, status=STATUS).items == ()


def test_embed_course_new_index_removes_old_vectors_and_vacuums(tmp_path: Path) -> None:
    context = make_context(tmp_path=tmp_path, fake=FakeEmbedder())
    course = write_course(store=context.store)
    write_pages(store=context.store, course=course, texts=["Nuovo testo"])
    context.vectors.put_vectors(
        model_key=OLD_MODEL,
        vectors=[
            StoredVector(
                text_sha256=str(index),
                vector=(1.0,) * LARGE_DIMENSIONS,
                truncated=False,
            )
            for index in range(VECTOR_COUNT)
        ],
    )
    path = tmp_path / "vectors.sqlite3"
    before = path.stat().st_size

    result = embed_course(
        context=context, course_key=course.key, progress=lambda update: None
    )

    assert result.processed == result.total == 1
    with closing(sqlite3.connect(database=path)) as connection:
        assert connection.execute(
            "SELECT count(*) FROM vectors WHERE model_key = ?", (OLD_MODEL,)
        ).fetchone() == (0,)
        assert connection.execute("SELECT model_key FROM models").fetchall() == [
            (context.embedding.model_key,)
        ]
    assert path.stat().st_size < before


@pytest.mark.parametrize("manifest", [{}, {"unit": "pending"}])
def test_purge_obsolete_models_preserves_empty_or_partial_index(
    tmp_path: Path, manifest: dict[str, str]
) -> None:
    vectors = VectorStore(path=tmp_path / "vectors.sqlite3")
    old = StoredVector(text_sha256="hash", vector=(1.0,), truncated=False)
    vectors.put_vectors(model_key=OLD_MODEL, vectors=[old])
    vectors.sync_units(course="course", units=manifest)
    assert vectors.purge_obsolete_models(model_key=MODEL_KEY) == 0
    assert vectors.vectors_for_units(model_key=OLD_MODEL, units={"unit": "hash"}) == {
        "unit": old
    }
    vectors.sync_units(course="course", units={"unit": "hash"})
    vectors.put_vectors(model_key=MODEL_KEY, vectors=[old])
    assert vectors.purge_obsolete_models(model_key=MODEL_KEY) == 1
    assert vectors.vectors_for_units(model_key=OLD_MODEL, units={"unit": "hash"}) == {}


def test_purge_obsolete_models_waits_for_other_courses(tmp_path: Path) -> None:
    vectors = VectorStore(path=tmp_path / "vectors.sqlite3")
    old = StoredVector(text_sha256="hash", vector=(1.0,), truncated=False)
    vectors.put_vectors(model_key=OLD_MODEL, vectors=[old])
    vectors.put_vectors(model_key=MODEL_KEY, vectors=[old])
    vectors.sync_units(course="ready", units={"unit": "hash"})
    vectors.sync_units(course="pending", units={"unit": "pending"})
    assert vectors.purge_obsolete_models(model_key=MODEL_KEY) == 0
    assert vectors.vectors_for_units(model_key=OLD_MODEL, units={"unit": "hash"}) == {
        "unit": old
    }
    vectors.put_vectors(
        model_key=MODEL_KEY,
        vectors=[StoredVector(text_sha256="pending", vector=(1.0,), truncated=False)],
    )
    assert vectors.purge_obsolete_models(model_key=MODEL_KEY) == 1
    assert vectors.has_other_models(model_key=MODEL_KEY) is False

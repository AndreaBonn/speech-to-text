import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from vector_reconcile_fixtures import (
    FakeEmbedder,
    make_context,
    replace_lecture,
    write_course,
    write_lecture,
    write_pages,
)

from sbobina.document_models import DocumentStatus
from sbobina.embedding_prompts import EMBEDDING_PROMPT_VERSION
from sbobina.embedding_units import content_hash
from sbobina.ollama_embed import EmbeddingUnavailableError, ModelStatus
from sbobina.web.api_files import TRANSCRIPT_FILES
from sbobina.web.document_store import read_document_in, write_document
from sbobina.web.vector_reconcile import (
    EmbeddingProgress,
    _course_inputs,
    embed_course,
    embedding_model_key,
)
from sbobina.web.vector_store import Coverage, StoredVector


def test_course_inputs_unregistered_course_returns_only_lectures(
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path=tmp_path, fake=FakeEmbedder())
    write_lecture(store=context.store, texts=["Lecture text"])
    other = write_course(store=context.store, label="Storia")
    write_pages(store=context.store, course=other, texts=["Document text"])

    inputs = _course_inputs(store=context.store, course_key="diritto")

    assert [item.text for item in inputs] == ["Lecture text"]
    assert [
        item.text for item in _course_inputs(store=context.store, course_key=other.key)
    ] == ["Document text"]


def test_embed_course_sends_only_twenty_missing_texts(tmp_path: Path) -> None:
    fake = FakeEmbedder()
    context = make_context(tmp_path=tmp_path, fake=fake)
    course = write_course(store=context.store)
    texts = [f"Passaggio {index}" for index in range(120)]
    write_pages(store=context.store, course=course, texts=texts)
    context.vectors.put_vectors(
        model_key=context.embedding.model_key,
        vectors=[
            StoredVector(
                text_sha256=content_hash(text), vector=(1.0, 1.0), truncated=False
            )
            for text in texts[:100]
        ],
    )
    updates: list[EmbeddingProgress] = []

    result = embed_course(
        context=context, course_key=course.key, progress=updates.append
    )

    assert [item.text for call in fake.calls for item in call] == texts[100:]
    assert (result.processed, result.total, result.truncated) == (120, 120, 0)
    assert updates[0].processed == 100
    assert updates[-1] == result
    assert result.units_per_second > 0


def test_embed_course_keeps_first_batch_after_second_fails(tmp_path: Path) -> None:
    fake = FakeEmbedder(fail_batch=2)
    context = make_context(tmp_path=tmp_path, fake=fake)
    course = write_course(store=context.store)
    texts = [f"Passaggio {index}" for index in range(40)]
    write_pages(store=context.store, course=course, texts=texts)

    with pytest.raises(RuntimeError, match="interrupted"):
        embed_course(
            context=context, course_key=course.key, progress=lambda update: None
        )

    cached = context.vectors.vectors_for_units(
        model_key=context.embedding.model_key,
        units={text: content_hash(text) for text in texts},
    )
    assert set(cached) == set(texts[:32])
    assert cached[texts[0]].vector == (1.0, 1.0)
    assert context.vectors.coverage(
        course=course.key, model_key=context.embedding.model_key
    ) == Coverage(embedded=32, total=40, truncated=0)


def test_embed_course_reembeds_changed_window_and_drops_deleted_units(
    tmp_path: Path,
) -> None:
    fake = FakeEmbedder()
    context = make_context(tmp_path=tmp_path, fake=fake)
    course = write_course(store=context.store)
    first, second = "prima " * 250, "seconda " * 250
    path = write_lecture(store=context.store, texts=[first, second])
    embed_course(context=context, course_key=course.key, progress=lambda update: None)
    assert len(fake.calls[0]) == 2
    replace_lecture(path=path, texts=[first, "modificata " * 250])

    result = embed_course(
        context=context, course_key=course.key, progress=lambda update: None
    )

    assert [item.text for item in fake.calls[1]] == [("modificata " * 250).strip()]
    assert result.processed == result.total == 2
    path.unlink()
    result = embed_course(
        context=context, course_key=course.key, progress=lambda update: None
    )
    assert result.processed == result.total == 0
    assert len(fake.calls) == 2


def test_embed_course_excludes_not_ready_document(tmp_path: Path) -> None:
    fake = FakeEmbedder()
    context = make_context(tmp_path=tmp_path, fake=fake)
    course = write_course(store=context.store)
    write_pages(store=context.store, course=course, texts=["Pronto"])
    failed = write_pages(store=context.store, course=course, texts=["Non pronto"])
    write_document(
        courses_dir=context.store.courses_dir,
        document=replace(
            read_document_in(doc_dir=failed),
            status=DocumentStatus.EXTRACTING,
            pages=None,
        ),
    )

    result = embed_course(
        context=context, course_key=course.key, progress=lambda update: None
    )

    assert [item.text for call in fake.calls for item in call] == ["Pronto"]
    assert result.total == 1


def test_embed_course_counts_truncated_units_including_cached_duplicates(
    tmp_path: Path,
) -> None:
    fake = FakeEmbedder(truncated_text="Lungo")
    context = make_context(tmp_path=tmp_path, fake=fake)
    course = write_course(store=context.store)
    write_pages(store=context.store, course=course, texts=["Lungo", "Lungo", "Breve"])
    updates: list[EmbeddingProgress] = []

    embed_course(context=context, course_key=course.key, progress=updates.append)
    result = embed_course(
        context=context, course_key=course.key, progress=updates.append
    )

    assert [item.text for item in fake.calls[0]] == ["Lungo", "Breve"]
    assert (result.processed, result.total, result.truncated) == (3, 3, 2)
    assert updates[-1].truncated == 2
    assert len(fake.calls) == 1
    assert result.units_per_second == 0


def test_embed_course_prefers_corrected_transcript(tmp_path: Path) -> None:
    fake = FakeEmbedder()
    context = make_context(tmp_path=tmp_path, fake=fake)
    course = write_course(store=context.store)
    path = write_lecture(store=context.store, texts=["Originale"])
    replace_lecture(
        path=path.parent / TRANSCRIPT_FILES["corrected"], texts=["Corretto"]
    )

    embed_course(context=context, course_key=course.key, progress=lambda update: None)

    assert [item.text for item in fake.calls[0]] == ["Corretto"]


def test_embed_course_formats_document_but_hashes_raw_text(tmp_path: Path) -> None:
    fake = FakeEmbedder()
    context = make_context(tmp_path=tmp_path, fake=fake)
    context = replace(
        context, embedding=replace(context.embedding, model="embeddinggemma:300m")
    )
    course = write_course(store=context.store)
    write_pages(store=context.store, course=course, texts=["Testo grezzo"])

    embed_course(context=context, course_key=course.key, progress=lambda update: None)

    assert fake.calls[0][0].text == "title: none | text: Testo grezzo"
    assert context.vectors.vectors_for_units(
        model_key=context.embedding.model_key,
        units={"raw": content_hash("Testo grezzo")},
    )["raw"].vector == (1.0, 1.0)


def test_embed_course_rejects_wrong_dimensions_before_persisting(
    tmp_path: Path,
) -> None:
    fake = FakeEmbedder(dimensions=3)
    context = make_context(tmp_path=tmp_path, fake=fake)
    course = write_course(store=context.store)
    write_pages(store=context.store, course=course, texts=["Testo"])

    with pytest.raises(EmbeddingUnavailableError) as error:
        embed_course(
            context=context, course_key=course.key, progress=lambda update: None
        )

    assert error.value.reason == "bad_response"
    assert context.vectors.coverage(
        course=course.key, model_key=context.embedding.model_key
    ) == Coverage(embedded=0, total=1, truncated=0)
    fake.dimensions = 2
    result = embed_course(
        context=context, course_key=course.key, progress=lambda update: None
    )
    assert result.processed == result.total == 1


def test_embedding_model_key_changes_with_model_identity() -> None:
    status = ModelStatus(digest="digest", dimensions=2)
    key = embedding_model_key(model="model", status=status)
    assert f"@{EMBEDDING_PROMPT_VERSION}" in key
    assert key != embedding_model_key(model="other", status=status)
    assert key != embedding_model_key(
        model="model", status=replace(status, digest="other")
    )
    assert key != embedding_model_key(
        model="model", status=replace(status, dimensions=3)
    )


def test_embed_course_succeeds_when_old_model_purge_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeEmbedder()
    context = make_context(tmp_path=tmp_path, fake=fake)
    course = write_course(store=context.store)
    write_pages(store=context.store, course=course, texts=["Uno", "Due"])

    def busy(*, model_key: str) -> int:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(context.vectors, "purge_obsolete_models", busy)

    result = embed_course(
        context=context, course_key=course.key, progress=lambda update: None
    )

    assert (result.processed, result.total) == (2, 2)
    assert "Old embedding models not purged" in caplog.text
    coverage = context.vectors.coverage(
        course=course.key, model_key=context.embedding.model_key
    )
    assert coverage.embedded == 2

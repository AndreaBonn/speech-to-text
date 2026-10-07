import json
from dataclasses import replace
from pathlib import Path

import pytest
from hybrid_runtime_fixtures import enable_factory, indexed_runtime
from vector_reconcile_fixtures import write_course, write_lecture

from sbobina.generation_models import (
    GenerationFormat,
    GenerationRequest,
    GenerationStatus,
)
from sbobina.web.dense_factory import DenseRuntime
from sbobina.web.generation_runner import (
    GenerationJob,
    execute_generation,
    run_generation_stage,
)
from sbobina.web.generation_store import (
    create_generation,
    generation_path,
    load_generation,
    save_generation,
)
from sbobina.web.job_store import JobStore

REPLY = json.dumps(
    {
        "domande": [
            {
                "domanda": "Che colore?",
                "opzioni": ["nero", "bianco", "rosso", "verde"],
                "corretta": 0,
                "soluzione": "nero",
                "citazioni": [
                    {"passaggio": "P1", "testo": "gatto nero dorme sul tappeto"}
                ],
            }
        ]
    }
)


@pytest.fixture
def job(tmp_path: Path) -> GenerationJob:
    store = JobStore(data_dir=tmp_path)
    course = write_course(store=store)
    write_lecture(store=store, texts=["il gatto nero dorme sul tappeto rosso"])
    record = create_generation(
        courses_dir=store.courses_dir,
        course_id=course.id,
        request=GenerationRequest(
            format=GenerationFormat.MULTIPLE_CHOICE, count=1, topic="gatto"
        ),
    )
    return GenerationJob(
        store=store,
        course_id=course.id,
        course_key=course.key,
        index_path=tmp_path / "search.sqlite3",
        record=record,
    )


@pytest.mark.parametrize("reason", ["disabled", "model_missing", "unreachable"])
def test_generation_persists_fallback_reason(job: GenerationJob, reason: str) -> None:
    execute_generation(
        job=job,
        chat=lambda request: REPLY,
        model="fake",
        dense=DenseRuntime(reason=reason, model="qwen3-embedding:8b"),
    )
    saved = load_generation(
        courses_dir=job.store.courses_dir,
        course_id=job.course_id,
        gen_id=job.record.id,
    )
    path = generation_path(
        courses_dir=job.store.courses_dir,
        course_id=job.course_id,
        gen_id=job.record.id,
    )
    expected = {"mode": "bm25", "reason": reason}
    assert saved.status == GenerationStatus.DONE and len(saved.questions) == 1
    assert (
        saved.retrieval_mode
        == json.loads(path.read_text())["retrieval_mode"]
        == expected
    )


def test_generation_uses_dense_ranking_and_persists_report(job: GenerationJob) -> None:
    dense, client = indexed_runtime(store=job.store)
    execute_generation(job=job, chat=lambda request: REPLY, model="fake", dense=dense)
    saved = load_generation(
        courses_dir=job.store.courses_dir,
        course_id=job.course_id,
        gen_id=job.record.id,
    )
    assert saved.status == GenerationStatus.DONE and len(saved.questions) == 1
    assert saved.retrieval_mode is not None
    assert saved.retrieval_mode["mode"] == "dense"
    assert client.calls[0]["options"]["num_gpu"] == 0


def test_empty_topic_keeps_sampling_without_dense_query(job: GenerationJob) -> None:
    dense, client = indexed_runtime(store=job.store)
    execute_generation(
        job=replace(job, record=replace(job.record, topic="")),
        chat=lambda request: REPLY,
        model="fake",
        dense=dense,
    )
    saved = load_generation(
        courses_dir=job.store.courses_dir,
        course_id=job.course_id,
        gen_id=job.record.id,
    )
    assert saved.status == GenerationStatus.DONE and len(saved.questions) == 1
    assert saved.retrieval_mode is None and client.calls == []


def test_child_entry_builds_dense_with_shared_factory(
    job: GenerationJob,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = indexed_runtime(store=job.store)
    enable_factory(monkeypatch=monkeypatch, client=client)
    monkeypatch.setattr(
        "sbobina.llm_factory.build_from_settings",
        lambda **kwargs: lambda request: REPLY,
    )
    save_generation(
        courses_dir=job.store.courses_dir,
        course_id=job.course_id,
        record=replace(job.record, status=GenerationStatus.RUNNING),
    )
    run_generation_stage(course_dir=job.store.courses_dir / job.course_id)
    saved = load_generation(
        courses_dir=job.store.courses_dir,
        course_id=job.course_id,
        gen_id=job.record.id,
    )
    assert saved.retrieval_mode is not None and saved.retrieval_mode["mode"] == "dense"
    assert client.calls[0]["options"]["num_gpu"] == 0

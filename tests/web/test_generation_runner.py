from pathlib import Path

import pytest

from sbobina.correction import CorrectorUnavailableError
from sbobina.course_registry import get_or_create
from sbobina.generation_models import (
    GenerationFormat,
    GenerationRequest,
    GenerationStatus,
)
from sbobina.models import Segment, Transcript, Word, save_transcript
from sbobina.ollama_chat import ChatRequest
from sbobina.web.api_files import TRANSCRIPT_FILES
from sbobina.web.generation_runner import (
    BUDGET_MIN_WORDS,
    NUM_PREDICT_MIN,
    GenerationJob,
    compute_budget_words,
    compute_options,
    execute_generation,
)
from sbobina.web.generation_store import create_generation, load_generation
from sbobina.web.job_models import JobConfig
from sbobina.web.job_store import JobStore


def test_compute_options_scales_num_predict_with_count() -> None:
    few = compute_options(count=1, format_=GenerationFormat.MULTIPLE_CHOICE, model="m")
    many = compute_options(
        count=20, format_=GenerationFormat.MULTIPLE_CHOICE, model="m"
    )

    assert many.num_predict > few.num_predict
    assert few.num_predict >= NUM_PREDICT_MIN


def test_compute_budget_words_shrinks_as_num_predict_grows_but_keeps_floor() -> None:
    few = compute_options(count=1, format_=GenerationFormat.MULTIPLE_CHOICE, model="m")
    many = compute_options(
        count=20, format_=GenerationFormat.MULTIPLE_CHOICE, model="m"
    )

    budget_few = compute_budget_words(
        format_=GenerationFormat.MULTIPLE_CHOICE, options=few
    )
    budget_many = compute_budget_words(
        format_=GenerationFormat.MULTIPLE_CHOICE, options=many
    )

    assert budget_many < budget_few
    assert budget_many >= BUDGET_MIN_WORDS


def _write_lecture(store: JobStore, job_id: str) -> None:
    transcript = Transcript(
        source="lezione.m4a",
        model="large-v3",
        language="it",
        duration=1.0,
        segments=(
            Segment(
                start=0.0,
                end=1.0,
                words=(
                    Word(
                        start=0.0,
                        end=1.0,
                        text="il gatto nero dorme sul tappeto rosso ogni sera tranquilla",
                        probability=0.99,
                    ),
                ),
            ),
        ),
    )
    directory = store.jobs_dir / job_id
    directory.mkdir(parents=True, exist_ok=True)
    save_transcript(
        transcript=transcript, path=directory / TRANSCRIPT_FILES["original"]
    )


def _job(
    store: JobStore, course_id: str, course_key: str, request: GenerationRequest
) -> GenerationJob:
    record = create_generation(
        courses_dir=store.courses_dir, course_id=course_id, request=request
    )
    return GenerationJob(
        store=store,
        index_path=store.jobs_dir.parent / "search.sqlite3",
        course_id=course_id,
        course_key=course_key,
        record=record,
    )


VALID_REPLY = (
    '{"domande": [{"domanda": "Che colore ha il gatto?", '
    '"opzioni": ["nero", "bianco", "rosso", "verde"], "corretta": 0, '
    '"soluzione": "nero", "citazioni": [{"passaggio": "P1", '
    '"testo": "gatto nero dorme sul tappeto"}]}]}'
)


def test_execute_generation_persists_done_record_with_cited_question(
    tmp_path: Path,
) -> None:
    store = JobStore(data_dir=tmp_path)
    lecture = store.create(config=JobConfig(subject="Fisica"))
    _write_lecture(store=store, job_id=str(lecture.id))
    course = get_or_create(courses_dir=store.courses_dir, key="fisica", label="Fisica")
    request = GenerationRequest(
        format=GenerationFormat.MULTIPLE_CHOICE, count=1, topic="gatto"
    )
    job = _job(store=store, course_id=course.id, course_key="fisica", request=request)

    execute_generation(job=job, chat=lambda _request: VALID_REPLY, model="qwen-test")

    saved = load_generation(
        courses_dir=store.courses_dir, course_id=course.id, gen_id=job.record.id
    )
    assert saved.status == GenerationStatus.DONE
    assert len(saved.questions) == 1
    assert saved.questions[0].citations[0].job_id == str(lecture.id)


def test_execute_generation_with_no_lectures_persists_done_with_no_material(
    tmp_path: Path,
) -> None:
    store = JobStore(data_dir=tmp_path)
    course = get_or_create(courses_dir=store.courses_dir, key="vuoto", label="Vuoto")
    request = GenerationRequest(format=GenerationFormat.MULTIPLE_CHOICE, count=1)
    job = _job(store=store, course_id=course.id, course_key="vuoto", request=request)

    def _unexpected_call(_request: ChatRequest) -> str:
        raise AssertionError("no passages: chat must not be called")

    execute_generation(job=job, chat=_unexpected_call, model="qwen-test")

    saved = load_generation(
        courses_dir=store.courses_dir, course_id=course.id, gen_id=job.record.id
    )
    assert saved.status == GenerationStatus.DONE
    assert saved.questions == ()


def test_execute_generation_persists_failed_on_invalid_response(
    tmp_path: Path,
) -> None:
    store = JobStore(data_dir=tmp_path)
    lecture = store.create(config=JobConfig(subject="Fisica"))
    _write_lecture(store=store, job_id=str(lecture.id))
    course = get_or_create(courses_dir=store.courses_dir, key="fisica", label="Fisica")
    request = GenerationRequest(
        format=GenerationFormat.MULTIPLE_CHOICE, count=1, topic="gatto"
    )
    job = _job(store=store, course_id=course.id, course_key="fisica", request=request)

    execute_generation(job=job, chat=lambda _request: "not json", model="qwen-test")

    saved = load_generation(
        courses_dir=store.courses_dir, course_id=course.id, gen_id=job.record.id
    )
    assert saved.status == GenerationStatus.FAILED
    assert saved.error == "INVALID_RESPONSE"


def test_execute_generation_propagates_ollama_unavailable(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    lecture = store.create(config=JobConfig(subject="Fisica"))
    _write_lecture(store=store, job_id=str(lecture.id))
    course = get_or_create(courses_dir=store.courses_dir, key="fisica", label="Fisica")
    request = GenerationRequest(
        format=GenerationFormat.MULTIPLE_CHOICE, count=1, topic="gatto"
    )
    job = _job(store=store, course_id=course.id, course_key="fisica", request=request)

    def _unreachable(_request: ChatRequest) -> str:
        raise CorrectorUnavailableError("Ollama down")

    with pytest.raises(CorrectorUnavailableError):
        execute_generation(job=job, chat=_unreachable, model="qwen-test")

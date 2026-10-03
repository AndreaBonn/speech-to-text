from pathlib import Path

import pytest
from study_fixtures import FakeChat

from sbobina.correction import CorrectorUnavailableError
from sbobina.course_registry import get_or_create
from sbobina.generation_models import (
    GenerationFormat,
    GenerationRequest,
    GenerationSources,
    GenerationStatus,
)
from sbobina.models import Segment, Transcript, Word, save_transcript
from sbobina.ollama_chat import ChatRequest
from sbobina.settings import settings
from sbobina.web.api_files import TRANSCRIPT_FILES
from sbobina.web.generation_queue import transition_generation
from sbobina.web.generation_runner import (
    GenerationJob,
    execute_generation,
    run_generation_stage,
)
from sbobina.web.generation_store import (
    create_generation,
    load_generation,
    save_generation,
)
from sbobina.web.job_models import JobConfig
from sbobina.web.job_store import JobStore


def _write_lecture_with_text(store: JobStore, job_id: str, text: str) -> None:
    transcript = Transcript(
        source="lezione.m4a",
        model="large-v3",
        language="it",
        duration=1.0,
        segments=(
            Segment(
                start=0.0,
                end=1.0,
                words=(Word(start=0.0, end=1.0, text=text, probability=0.99),),
            ),
        ),
    )
    directory = store.jobs_dir / job_id
    directory.mkdir(parents=True, exist_ok=True)
    save_transcript(
        transcript=transcript, path=directory / TRANSCRIPT_FILES["original"]
    )


def _write_lecture(store: JobStore, job_id: str) -> None:
    _write_lecture_with_text(
        store=store,
        job_id=job_id,
        text="il gatto nero dorme sul tappeto rosso ogni sera tranquilla",
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


def test_execute_generation_with_empty_topic_samples_the_whole_course(
    tmp_path: Path,
) -> None:
    # B1 regression: an empty topic used to mean an empty FTS match, so the
    # course's own material never reached the chat even with lectures to cite.
    store = JobStore(data_dir=tmp_path)
    lecture = store.create(config=JobConfig(subject="Fisica"))
    _write_lecture(store=store, job_id=str(lecture.id))
    course = get_or_create(courses_dir=store.courses_dir, key="fisica", label="Fisica")
    request = GenerationRequest(format=GenerationFormat.MULTIPLE_CHOICE, count=1)
    job = _job(store=store, course_id=course.id, course_key="fisica", request=request)
    fake_chat = FakeChat(responses=[VALID_REPLY])

    execute_generation(job=job, chat=fake_chat, model="qwen-test")

    saved = load_generation(
        courses_dir=store.courses_dir, course_id=course.id, gen_id=job.record.id
    )
    assert len(fake_chat.requests) == 1
    assert saved.status == GenerationStatus.DONE
    assert len(saved.questions) == 1


def test_execute_generation_with_empty_topic_restricts_sampling_to_selected_source(
    tmp_path: Path,
) -> None:
    # B2 regression: request.sources was never persisted nor applied, so an
    # explicit source selection was silently ignored.
    store = JobStore(data_dir=tmp_path)
    lecture_a = store.create(config=JobConfig(subject="Fisica"))
    lecture_b = store.create(config=JobConfig(subject="Fisica"))
    _write_lecture(store=store, job_id=str(lecture_a.id))
    _write_lecture_with_text(
        store=store,
        job_id=str(lecture_b.id),
        text="balena blu nuota nell'oceano profondo e silenzioso",
    )
    course = get_or_create(courses_dir=store.courses_dir, key="fisica", label="Fisica")
    request = GenerationRequest(
        format=GenerationFormat.MULTIPLE_CHOICE,
        count=1,
        sources=GenerationSources(job_ids=(str(lecture_a.id),)),
    )
    job = _job(store=store, course_id=course.id, course_key="fisica", request=request)
    fake_chat = FakeChat(responses=[VALID_REPLY])

    execute_generation(job=job, chat=fake_chat, model="qwen-test")

    user_message = fake_chat.requests[0].user_message
    assert "balena" not in user_message
    assert "gatto" in user_message


def test_execute_generation_with_topic_restricts_retrieval_to_selected_source(
    tmp_path: Path,
) -> None:
    # B2, the question path: both lectures match "gatto", only lecture_a is
    # selected.
    store = JobStore(data_dir=tmp_path)
    lecture_a = store.create(config=JobConfig(subject="Fisica"))
    lecture_b = store.create(config=JobConfig(subject="Fisica"))
    _write_lecture(store=store, job_id=str(lecture_a.id))
    _write_lecture_with_text(
        store=store,
        job_id=str(lecture_b.id),
        text="il gatto bianco dorme sul divano blu ogni notte silenziosa",
    )
    course = get_or_create(courses_dir=store.courses_dir, key="fisica", label="Fisica")
    request = GenerationRequest(
        format=GenerationFormat.MULTIPLE_CHOICE,
        count=1,
        topic="gatto",
        sources=GenerationSources(job_ids=(str(lecture_a.id),)),
    )
    job = _job(store=store, course_id=course.id, course_key="fisica", request=request)
    fake_chat = FakeChat(responses=[VALID_REPLY])

    execute_generation(job=job, chat=fake_chat, model="qwen-test")

    user_message = fake_chat.requests[0].user_message
    assert "bianco" not in user_message
    assert "nero" in user_message


def test_run_generation_stage_completes_the_running_generation_of_the_course_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = JobStore(data_dir=tmp_path)
    lecture = store.create(config=JobConfig(subject="Fisica"))
    _write_lecture(store=store, job_id=str(lecture.id))
    course = get_or_create(courses_dir=store.courses_dir, key="fisica", label="Fisica")
    queued = create_generation(
        courses_dir=store.courses_dir,
        course_id=course.id,
        request=GenerationRequest(
            format=GenerationFormat.MULTIPLE_CHOICE, count=1, topic="gatto"
        ),
    )
    save_generation(
        courses_dir=store.courses_dir,
        course_id=course.id,
        record=transition_generation(record=queued, status=GenerationStatus.RUNNING),
    )
    ensured: list[str] = []
    monkeypatch.setattr(
        "sbobina.web.generation_runner.llm_corrector.ensure_model",
        lambda model, host: ensured.append(model),
    )
    monkeypatch.setattr(
        "sbobina.web.generation_runner.ollama_chat.chat_json",
        lambda client, request: VALID_REPLY,
    )

    run_generation_stage(course_dir=store.courses_dir / course.id)

    saved = load_generation(
        courses_dir=store.courses_dir, course_id=course.id, gen_id=queued.id
    )
    assert ensured == [settings.ollama_model]
    assert saved.status == GenerationStatus.DONE
    assert saved.questions[0].citations[0].job_id == str(lecture.id)

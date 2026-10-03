import logging
from dataclasses import replace
from pathlib import Path

import pytest

from sbobina.generation_models import (
    GenerationFormat,
    GenerationRequest,
    GenerationSources,
    GenerationStatus,
)
from sbobina.web.errors import NotFoundError
from sbobina.web.generation_queue import finish_generation
from sbobina.web.generation_store import (
    create_generation,
    find_running,
    generation_dir,
    iter_generations,
    load_generation,
    save_generation,
)

REQUEST = GenerationRequest(format=GenerationFormat.MULTIPLE_CHOICE, count=1)


def test_create_generation_persists_requested_sources(tmp_path: Path) -> None:
    request = GenerationRequest(
        format=GenerationFormat.MULTIPLE_CHOICE,
        count=1,
        sources=GenerationSources(doc_ids=("doc1",), job_ids=("job1",)),
    )

    record = create_generation(courses_dir=tmp_path, course_id="corso", request=request)

    assert record.requested_sources == request.sources


def test_create_generation_defaults_requested_sources_when_none_given(
    tmp_path: Path,
) -> None:
    record = create_generation(courses_dir=tmp_path, course_id="corso", request=REQUEST)

    assert record.requested_sources == GenerationSources()


def test_find_running_skips_corrupt_sibling_record(tmp_path: Path) -> None:
    record = create_generation(courses_dir=tmp_path, course_id="corso", request=REQUEST)
    running = replace(record, status=GenerationStatus.RUNNING)
    save_generation(courses_dir=tmp_path, course_id="corso", record=running)
    # "0.json" sorts before any uuid name, so the corrupt file is read first.
    corrupt = generation_dir(courses_dir=tmp_path, course_id="corso") / "0.json"
    corrupt.write_text("{", encoding="utf-8")

    found = find_running(courses_dir=tmp_path, course_id="corso")

    assert found.id == record.id


def test_iter_generations_skips_corrupt_record_and_yields_every_course(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    first = create_generation(courses_dir=tmp_path, course_id="uno", request=REQUEST)
    second = create_generation(courses_dir=tmp_path, course_id="due", request=REQUEST)
    corrupt = generation_dir(courses_dir=tmp_path, course_id="uno") / "rotto.json"
    corrupt.write_text("{", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        found = sorted(
            (course, record.id) for course, record in iter_generations(tmp_path)
        )

    assert found == sorted([("uno", first.id), ("due", second.id)])
    assert "rotto.json" in caplog.text


def test_find_running_without_a_running_record_is_not_found(tmp_path: Path) -> None:
    create_generation(courses_dir=tmp_path, course_id="corso", request=REQUEST)

    with pytest.raises(NotFoundError):
        find_running(courses_dir=tmp_path, course_id="corso")


def test_find_running_course_without_generations_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(NotFoundError):
        find_running(courses_dir=tmp_path, course_id="corso")


def test_finish_generation_records_the_outcome_of_a_running_generation(
    tmp_path: Path,
) -> None:
    record = create_generation(courses_dir=tmp_path, course_id="corso", request=REQUEST)
    running = replace(record, status=GenerationStatus.RUNNING)
    save_generation(courses_dir=tmp_path, course_id="corso", record=running)

    finish_generation(
        courses_dir=tmp_path,
        course_id="corso",
        gen_id=record.id,
        status=GenerationStatus.FAILED,
        error="OLLAMA_UNAVAILABLE",
    )

    saved = load_generation(courses_dir=tmp_path, course_id="corso", gen_id=record.id)
    assert (saved.status, saved.error) == (
        GenerationStatus.FAILED,
        "OLLAMA_UNAVAILABLE",
    )


def test_finish_generation_never_overwrites_an_interrupted_generation(
    tmp_path: Path,
) -> None:
    record = create_generation(courses_dir=tmp_path, course_id="corso", request=REQUEST)
    interrupted = replace(record, status=GenerationStatus.INTERRUPTED)
    save_generation(courses_dir=tmp_path, course_id="corso", record=interrupted)

    finish_generation(
        courses_dir=tmp_path,
        course_id="corso",
        gen_id=record.id,
        status=GenerationStatus.FAILED,
        error="CRASH",
    )

    saved = load_generation(courses_dir=tmp_path, course_id="corso", gen_id=record.id)
    assert (saved.status, saved.error) == (GenerationStatus.INTERRUPTED, None)

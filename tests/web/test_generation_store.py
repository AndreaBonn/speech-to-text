from dataclasses import replace
from pathlib import Path

from sbobina.generation_models import (
    GenerationFormat,
    GenerationRequest,
    GenerationSources,
    GenerationStatus,
)
from sbobina.web.generation_store import (
    create_generation,
    find_running,
    generation_dir,
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

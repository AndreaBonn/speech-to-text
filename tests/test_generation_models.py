import json
from dataclasses import asdict, replace

import pytest

from sbobina.generation_models import (
    DiscardCount,
    GenerationCitation,
    GenerationFormat,
    GenerationQuestion,
    GenerationRecord,
    GenerationSources,
    GenerationSourceUsed,
    GenerationStatus,
    SummarySection,
    SummarySentence,
    dump_generation,
    load_generation,
)


def test_generation_question_rejects_wrong_option_count() -> None:
    with pytest.raises(ValueError, match="expected 4 options"):
        GenerationQuestion(
            question="q",
            options=("a", "b", "c"),
            correct_index=0,
            solution="s",
            citations=(),
        )


def test_generation_question_rejects_correct_index_out_of_range() -> None:
    with pytest.raises(ValueError, match="correct_index"):
        GenerationQuestion(
            question="q",
            options=("a", "b", "c", "d"),
            correct_index=4,
            solution="s",
            citations=(),
        )


def test_generation_question_rejects_correct_index_without_options() -> None:
    with pytest.raises(ValueError, match="correct_index is set without options"):
        GenerationQuestion(
            question="q", options=(), correct_index=0, solution="s", citations=()
        )


def test_generation_question_accepts_open_question_without_options() -> None:
    question = GenerationQuestion(
        question="q", options=(), correct_index=None, solution="s", citations=()
    )
    assert question.options == ()
    assert question.correct_index is None


def test_generation_source_used_rejects_both_doc_and_job_id() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        GenerationSourceUsed(doc_id="d1", sha256="abc", job_id="j1", revision="r1")


def test_generation_source_used_rejects_neither_doc_nor_job_id() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        GenerationSourceUsed(doc_id=None, sha256=None, job_id=None, revision=None)


def test_generation_source_used_accepts_document_source() -> None:
    source = GenerationSourceUsed(doc_id="d1", sha256="abc", job_id=None, revision=None)
    assert source.doc_id == "d1"


def test_generation_source_used_accepts_lecture_source() -> None:
    source = GenerationSourceUsed(doc_id=None, sha256=None, job_id="j1", revision="r1")
    assert source.job_id == "j1"


def _base_record() -> GenerationRecord:
    return GenerationRecord(
        id="gen-1",
        format=GenerationFormat.MULTIPLE_CHOICE,
        status=GenerationStatus.QUEUED,
        requested_count=5,
        topic="causa del contratto",
        model="qwen3.5:9b",
        prompt_version="compito-v1",
        generated_at="2026-10-03T10:00:00Z",
        sources=(),
        discarded=(),
        questions=(),
        sections=(),
        error=None,
    )


def test_generation_record_defaults_requested_sources_when_omitted() -> None:
    assert _base_record().requested_sources == GenerationSources()


def test_load_generation_accepts_json_without_requested_sources() -> None:
    # Backward compat: a record saved before T034 has no requested_sources
    # key at all, not an explicit empty one.
    payload = json.loads(dump_generation(record=_base_record()))
    del payload["requested_sources"]

    loaded = load_generation(content=json.dumps(payload))

    assert loaded.requested_sources == GenerationSources()


def _mc_question(citations: tuple[GenerationCitation, ...] = ()) -> GenerationQuestion:
    return GenerationQuestion(
        question="q",
        options=("a", "b", "c", "d"),
        correct_index=0,
        solution="s",
        citations=citations,
    )


def test_generation_record_rejects_questions_while_queued() -> None:
    with pytest.raises(ValueError, match="content is set only when done"):
        replace(_base_record(), questions=(_mc_question(),))


def test_generation_record_rejects_error_without_failed_status() -> None:
    with pytest.raises(ValueError, match="error is set only when failed"):
        replace(_base_record(), error="boom")


def test_generation_record_rejects_failed_status_without_error() -> None:
    with pytest.raises(ValueError, match="error is set only when failed"):
        replace(_base_record(), status=GenerationStatus.FAILED)


def test_generation_record_rejects_sections_on_non_summary_format() -> None:
    with pytest.raises(ValueError, match="sections are set only for the summary"):
        replace(
            _base_record(),
            status=GenerationStatus.DONE,
            sections=(SummarySection(title="t", sentences=()),),
        )


def test_generation_record_rejects_options_on_summary_format() -> None:
    with pytest.raises(ValueError, match="questions are set for a summary"):
        replace(
            _base_record(),
            format=GenerationFormat.SUMMARY,
            status=GenerationStatus.DONE,
            questions=(_mc_question(),),
        )


def test_generation_record_rejects_mc_options_for_open_format() -> None:
    with pytest.raises(ValueError, match="options are set for a"):
        replace(
            _base_record(),
            format=GenerationFormat.OPEN,
            status=GenerationStatus.DONE,
            questions=(_mc_question(),),
        )


def test_generation_record_accepts_done_status_with_matching_content() -> None:
    record = replace(
        _base_record(),
        status=GenerationStatus.DONE,
        questions=(
            _mc_question(
                citations=(
                    GenerationCitation(
                        passage_id="manuale:p214:c0",
                        quote="testo citato qui",
                        doc_id="manuale",
                        page=214,
                        job_id=None,
                        timestamp=None,
                    ),
                )
            ),
        ),
    )
    assert record.questions[0].question == "q"


def test_generation_record_json_round_trip_is_identical() -> None:
    record = GenerationRecord(
        id="gen-2",
        format=GenerationFormat.SUMMARY,
        status=GenerationStatus.DONE,
        requested_count=1,
        topic="avviamento",
        model="qwen3.5:9b",
        prompt_version="riassunto-v1",
        generated_at="2026-10-03T10:00:00Z",
        sources=(
            GenerationSourceUsed(
                doc_id="d1", sha256="abc123", job_id=None, revision=None
            ),
            GenerationSourceUsed(
                doc_id=None, sha256=None, job_id="j1", revision="rev1"
            ),
        ),
        discarded=(DiscardCount(reason="QUOTE_NOT_FOUND", count=2),),
        questions=(),
        sections=(
            SummarySection(
                title="Avviamento",
                sentences=(
                    SummarySentence(
                        text="L'avviamento produce profitto.",
                        citations=(
                            GenerationCitation(
                                passage_id="manuale:p12:c0",
                                quote="capacita' di produrre profitto",
                                doc_id="manuale",
                                page=12,
                                job_id=None,
                                timestamp=None,
                            ),
                        ),
                    ),
                ),
            ),
        ),
        error=None,
    )
    dumped = dump_generation(record=record)
    reloaded = load_generation(content=dumped)
    assert reloaded == record
    # requested_sources is a pydantic model, not a dataclass: asdict() leaves
    # it as an object instead of recursing into it like it does for the
    # GenerationSourceUsed/GenerationCitation dataclasses above.
    expected = asdict(record)
    expected["requested_sources"] = record.requested_sources.model_dump()
    assert json.loads(dumped) == json.loads(json.dumps(expected, default=str))


def test_generation_record_rejects_multiple_choice_question_without_options() -> None:
    open_question = GenerationQuestion(
        question="q", options=(), correct_index=None, solution="s", citations=()
    )
    with pytest.raises(ValueError, match="needs its options"):
        replace(
            _base_record(),
            status=GenerationStatus.DONE,
            questions=(open_question,),
        )
    done = replace(
        _base_record(), status=GenerationStatus.DONE, questions=(_mc_question(),)
    )
    assert done.questions[0].options == ("a", "b", "c", "d")


def test_discard_count_rejects_negative_count() -> None:
    with pytest.raises(ValueError):
        DiscardCount(reason="QUOTE_NOT_FOUND", count=-1)
    assert DiscardCount(reason="QUOTE_NOT_FOUND", count=0).count == 0


@pytest.mark.parametrize(
    "options", [("a", "a", "c", "d"), ("a", " ", "c", "d")], ids=["duplicate", "blank"]
)
def test_generation_question_rejects_duplicate_or_blank_options(
    options: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="options"):
        GenerationQuestion(
            question="q", options=options, correct_index=0, solution="s", citations=()
        )

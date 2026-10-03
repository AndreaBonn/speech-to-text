import json
from dataclasses import asdict, replace

import pytest
from pydantic import ValidationError

from sbobina.generation_models import (
    DiscardCount,
    GenerationCitation,
    GenerationFormat,
    GenerationQuestion,
    GenerationRecord,
    GenerationRequest,
    GenerationSources,
    GenerationSourceUsed,
    GenerationStatus,
    MultipleChoiceResponse,
    SummaryResponse,
    SummarySection,
    SummarySentence,
    TextQuestionResponse,
    dump_generation,
    load_generation,
)


def _mc_payload(options: list[str], correct_index: int) -> dict[str, object]:
    return {
        "domande": [
            {
                "domanda": "Quando la causa e' illecita?",
                "opzioni": options,
                "corretta": correct_index,
                "soluzione": "Il manuale lo spiega.",
                "citazioni": [
                    {"passaggio": "P2", "testo": "contraria a norme imperative"}
                ],
            }
        ]
    }


def test_multiple_choice_response_rejects_three_options() -> None:
    with pytest.raises(ValidationError):
        MultipleChoiceResponse.model_validate(
            _mc_payload(options=["a", "b", "c"], correct_index=0)
        )


def test_multiple_choice_response_rejects_correct_index_out_of_range() -> None:
    with pytest.raises(ValidationError):
        MultipleChoiceResponse.model_validate(
            _mc_payload(options=["a", "b", "c", "d"], correct_index=4)
        )


def test_multiple_choice_response_accepts_four_options_one_correct() -> None:
    response = MultipleChoiceResponse.model_validate(
        _mc_payload(options=["a", "b", "c", "d"], correct_index=1)
    )
    question = response.questions[0]
    assert question.options == ["a", "b", "c", "d"]
    assert question.correct_index == 1
    assert question.citations[0].passage == "P2"


def test_multiple_choice_response_accepts_empty_question_list() -> None:
    assert MultipleChoiceResponse.model_validate({"domande": []}).questions == []


@pytest.mark.parametrize("passage", ["2", "p2", "P-1", "P2x", None])
def test_proposed_citation_rejects_malformed_passage_reference(passage: object) -> None:
    with pytest.raises(ValidationError):
        MultipleChoiceResponse.model_validate(
            {
                "domande": [
                    {
                        "domanda": "d",
                        "opzioni": ["a", "b", "c", "d"],
                        "corretta": 0,
                        "soluzione": "s",
                        "citazioni": [{"passaggio": passage, "testo": "testo citato"}],
                    }
                ]
            }
        )


def test_text_question_response_has_no_options_or_correct_index() -> None:
    response = TextQuestionResponse.model_validate(
        {
            "domande": [
                {
                    "domanda": "Cosa caratterizza lo stato stazionario?",
                    "soluzione": "Gli investimenti coprono l'ammortamento.",
                    "citazioni": [
                        {"passaggio": "P5", "testo": "capitate per occupato"}
                    ],
                }
            ]
        }
    )
    question = response.questions[0]
    assert question.solution == "Gli investimenti coprono l'ammortamento."
    assert not hasattr(question, "options")


def test_text_question_response_accepts_empty_question_list() -> None:
    assert TextQuestionResponse.model_validate({"domande": []}).questions == []


def test_summary_response_parses_sections_and_sentences() -> None:
    response = SummaryResponse.model_validate(
        {
            "sezioni": [
                {
                    "titolo": "Avviamento",
                    "frasi": [
                        {
                            "testo": "L'avviamento produce profitto.",
                            "citazioni": [
                                {
                                    "passaggio": "P4",
                                    "testo": "capacita' di produrre profitto",
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    )
    section = response.sections[0]
    assert section.title == "Avviamento"
    assert section.sentences[0].text == "L'avviamento produce profitto."


def test_summary_response_accepts_empty_sections() -> None:
    assert SummaryResponse.model_validate({"sezioni": []}).sections == []


@pytest.mark.parametrize("count", [0, 11])
def test_generation_request_rejects_out_of_range_count(count: int) -> None:
    with pytest.raises(ValidationError) as excinfo:
        GenerationRequest.model_validate({"format": "multiple_choice", "count": count})
    assert excinfo.value.errors()[0]["loc"] == ("count",)


def test_generation_request_accepts_boundary_counts() -> None:
    for count in (1, 10):
        request = GenerationRequest.model_validate({"format": "open", "count": count})
        assert request.count == count


def test_generation_request_rejects_topic_over_200_characters() -> None:
    with pytest.raises(ValidationError) as excinfo:
        GenerationRequest.model_validate(
            {"format": "summary", "count": 1, "topic": "x" * 201}
        )
    assert excinfo.value.errors()[0]["loc"] == ("topic",)


def test_generation_request_accepts_empty_topic_and_defaults_sources() -> None:
    request = GenerationRequest.model_validate({"format": "summary", "count": 5})
    assert request.topic == ""
    assert request.sources.doc_ids == ()
    assert request.sources.job_ids == ()


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


def test_generation_citation_rejects_both_doc_and_job_id() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        GenerationCitation(
            passage_id="p1",
            quote="q",
            doc_id="d1",
            page=1,
            job_id="j1",
            timestamp=1.0,
        )


def test_generation_citation_rejects_neither_doc_nor_job_id() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        GenerationCitation(
            passage_id="p1",
            quote="q",
            doc_id=None,
            page=None,
            job_id=None,
            timestamp=None,
        )


def test_generation_citation_rejects_page_without_doc_id() -> None:
    with pytest.raises(ValueError, match="page is set only"):
        GenerationCitation(
            passage_id="p1",
            quote="q",
            doc_id=None,
            page=1,
            job_id="j1",
            timestamp=1.0,
        )


def test_generation_citation_rejects_timestamp_without_job_id() -> None:
    with pytest.raises(ValueError, match="timestamp is set only"):
        GenerationCitation(
            passage_id="p1",
            quote="q",
            doc_id="d1",
            page=1,
            job_id=None,
            timestamp=1.0,
        )


def test_generation_citation_accepts_document_location() -> None:
    citation = GenerationCitation(
        passage_id="manuale:p214:c0",
        quote="q",
        doc_id="manuale",
        page=214,
        job_id=None,
        timestamp=None,
    )
    assert citation.doc_id == "manuale"
    assert citation.page == 214


def test_generation_citation_accepts_lecture_location() -> None:
    citation = GenerationCitation(
        passage_id="Ljob-1-S3",
        quote="q",
        doc_id=None,
        page=None,
        job_id="job-1",
        timestamp=42.5,
    )
    assert citation.job_id == "job-1"
    assert citation.timestamp == 42.5


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

import pytest
from pydantic import ValidationError

from sbobina.generation_models import (
    GenerationRequest,
    MultipleChoiceResponse,
    SummaryResponse,
    TextQuestionResponse,
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

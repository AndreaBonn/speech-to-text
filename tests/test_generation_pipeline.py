import json

import pytest
from study_fixtures import FakeChat

from sbobina.generation_models import GenerationFormat, GenerationRequest
from sbobina.generation_pipeline import (
    GenerationOptions,
    GenerationOutcome,
    estimate_tokens,
    generate,
)
from sbobina.ollama_chat import CONTEXT_WINDOW_TOKENS
from sbobina.retrieval import DocumentSource, RetrievedPassage, cut_to_budget
from sbobina.web.generation_runner import compute_budget_words


def _doc_passage(
    page: int = 214,
    text: str = "la causa e' illecita quando contraria a norme imperative",
) -> RetrievedPassage:
    return RetrievedPassage(
        text=text,
        source=DocumentSource(doc_id="manuale", page=page, chunk=0),
        passage_id=f"manuale:p{page}:c0",
    )


def _options(num_predict: int = 1024) -> GenerationOptions:
    return GenerationOptions(model="test", num_predict=num_predict)


def _mc_request(count: int = 1, topic: str = "") -> GenerationRequest:
    return GenerationRequest.model_validate(
        {"format": "multiple_choice", "count": count, "topic": topic}
    )


def _mc_payload(citation_text: str) -> str:
    return json.dumps(
        {
            "domande": [
                {
                    "domanda": "Quando la causa e' illecita?",
                    "opzioni": ["a", "b", "c", "d"],
                    "corretta": 1,
                    "soluzione": "Il manuale lo spiega.",
                    "citazioni": [{"passaggio": "P1", "testo": citation_text}],
                }
            ]
        }
    )


def test_generate_discards_question_with_uncited_solution_and_counts_it() -> None:
    chat = FakeChat(responses=[_mc_payload("parole mai scritte nel passaggio")])

    result = generate(
        request=_mc_request(), passages=[_doc_passage()], chat=chat, options=_options()
    )

    assert result.outcome == GenerationOutcome.DONE
    assert result.questions == ()
    assert sum(d.count for d in result.discarded) == 1
    assert {d.reason for d in result.discarded} == {"QUOTE_NOT_FOUND"}


def test_generate_keeps_question_with_cited_solution() -> None:
    chat = FakeChat(responses=[_mc_payload("la causa e' illecita quando contraria")])

    result = generate(
        request=_mc_request(), passages=[_doc_passage()], chat=chat, options=_options()
    )

    assert len(result.questions) == 1
    assert result.questions[0].citations[0].passage_id == "manuale:p214:c0"
    assert result.questions[0].citations[0].doc_id == "manuale"
    assert result.discarded == ()


def test_generate_returns_no_material_without_calling_chat_when_no_passages() -> None:
    chat = FakeChat(responses=["should never be read"])

    result = generate(
        request=_mc_request(topic="argomento assente"),
        passages=[],
        chat=chat,
        options=_options(),
    )

    assert result.outcome == GenerationOutcome.NO_MATERIAL
    assert chat.requests == []


def test_generate_retries_invalid_json_then_succeeds() -> None:
    chat = FakeChat(
        responses=["{", _mc_payload("la causa e' illecita quando contraria")]
    )

    result = generate(
        request=_mc_request(), passages=[_doc_passage()], chat=chat, options=_options()
    )

    assert len(result.questions) == 1
    assert len(chat.requests) == 2


def test_generate_fails_after_exhausting_retries_on_invalid_json() -> None:
    chat = FakeChat(responses=["{", "{"])

    result = generate(
        request=_mc_request(), passages=[_doc_passage()], chat=chat, options=_options()
    )

    assert result.outcome == GenerationOutcome.FAILED
    assert result.error == "INVALID_RESPONSE"
    assert result.questions == ()


def test_generate_discards_multiple_choice_with_duplicate_options() -> None:
    payload = json.loads(_mc_payload("la causa e' illecita quando contraria"))
    payload["domande"][0]["opzioni"] = ["a", "a", "c", "d"]
    chat = FakeChat(responses=[json.dumps(payload)])

    result = generate(
        request=_mc_request(), passages=[_doc_passage()], chat=chat, options=_options()
    )

    assert result.questions == ()
    assert {d.reason for d in result.discarded} == {"INVALID_OPTIONS"}


def test_generate_discards_question_with_four_citations() -> None:
    payload = json.loads(_mc_payload("la causa e' illecita quando contraria"))
    payload["domande"][0]["citazioni"] = [
        {"passaggio": "P1", "testo": "la causa e' illecita quando contraria"}
    ] * 4
    chat = FakeChat(responses=[json.dumps(payload)])

    result = generate(
        request=_mc_request(), passages=[_doc_passage()], chat=chat, options=_options()
    )

    assert result.questions == ()
    assert {d.reason for d in result.discarded} == {"CITATION_COUNT"}


def test_generate_discards_question_with_zero_citations() -> None:
    payload = json.loads(_mc_payload("la causa e' illecita quando contraria"))
    payload["domande"][0]["citazioni"] = []
    chat = FakeChat(responses=[json.dumps(payload)])

    result = generate(
        request=_mc_request(), passages=[_doc_passage()], chat=chat, options=_options()
    )

    assert result.questions == ()
    assert {d.reason for d in result.discarded} == {"CITATION_COUNT"}


def test_generate_summary_resolves_citations_and_counts_discards() -> None:
    passages = [_doc_passage(text="l'avviamento produce profitto per l'azienda")]
    payload = json.dumps(
        {
            "sezioni": [
                {
                    "titolo": "Avviamento",
                    "frasi": [
                        {
                            "testo": "buona",
                            "citazioni": [
                                {
                                    "passaggio": "P1",
                                    "testo": "l'avviamento produce profitto",
                                }
                            ],
                        },
                        {
                            "testo": "scartata",
                            "citazioni": [
                                {"passaggio": "P1", "testo": "frase mai scritta"}
                            ],
                        },
                    ],
                }
            ]
        }
    )
    chat = FakeChat(responses=[payload])

    result = generate(
        request=GenerationRequest.model_validate({"format": "summary", "count": 1}),
        passages=passages,
        chat=chat,
        options=_options(),
    )

    assert len(result.sections) == 1
    assert len(result.sections[0].sentences) == 1
    assert sum(d.count for d in result.discarded) == 1


def test_build_prompt_for_twelve_passages_stays_under_token_budget_with_output_margin() -> (
    None
):
    # The material budget comes from the real system prompt's length
    # (compute_budget_words), so a longer prompt version shrinks it.
    passage_text = " ".join(f"parola{i}" for i in range(190))
    options = _options(num_predict=1024)
    budget = compute_budget_words(
        format_=GenerationFormat.MULTIPLE_CHOICE, options=options
    )
    passages = cut_to_budget(
        ranked=[_doc_passage(page=n, text=passage_text) for n in range(1, 13)],
        budget_words=budget,
    )
    chat = FakeChat(responses=['{"domande": []}'])

    generate(
        request=_mc_request(count=5, topic="argomento"),
        passages=passages,
        chat=chat,
        options=options,
    )

    sent = chat.requests[0]
    total = estimate_tokens(sent.system_prompt) + estimate_tokens(sent.user_message)
    assert total + options.num_predict <= CONTEXT_WINDOW_TOKENS


def test_generate_keeps_question_dropping_only_its_invented_citation() -> None:
    # Same rule as the chat (T046): an invented citation goes, the question
    # stays while one of its citations is in the material.
    payload = json.loads(_mc_payload("la causa e' illecita quando contraria"))
    payload["domande"][0]["citazioni"].append(
        {"passaggio": "P1", "testo": "parole mai scritte nel passaggio"}
    )
    chat = FakeChat(responses=[json.dumps(payload)])

    result = generate(
        request=_mc_request(), passages=[_doc_passage()], chat=chat, options=_options()
    )

    [question] = result.questions
    assert [c.quote for c in question.citations] == [
        "la causa e' illecita quando contraria"
    ]
    assert result.discarded == ()


def _text_payload(citation_text: str) -> str:
    return json.dumps(
        {
            "domande": [
                {
                    "domanda": "Spiega quando la causa e' illecita.",
                    "soluzione": "Quando contraria a norme imperative.",
                    "citazioni": [{"passaggio": "P1", "testo": citation_text}],
                }
            ]
        }
    )


@pytest.mark.parametrize("format_", ["open", "oral"])
def test_generate_text_question_keeps_cited_solution_without_options(
    format_: str,
) -> None:
    request = GenerationRequest.model_validate({"format": format_, "count": 1})
    chat = FakeChat(responses=[_text_payload("contraria a norme imperative")])

    result = generate(
        request=request, passages=[_doc_passage()], chat=chat, options=_options()
    )

    [question] = result.questions
    assert (question.options, question.correct_index) == ((), None)
    assert question.solution == "Quando contraria a norme imperative."
    assert [c.passage_id for c in question.citations] == ["manuale:p214:c0"]


def test_generate_text_question_with_uncited_solution_is_discarded() -> None:
    request = GenerationRequest.model_validate({"format": "open", "count": 1})
    chat = FakeChat(responses=[_text_payload("parole mai scritte nel passaggio")])

    result = generate(
        request=request, passages=[_doc_passage()], chat=chat, options=_options()
    )

    assert result.questions == ()
    assert {(d.reason, d.count) for d in result.discarded} == {("QUOTE_NOT_FOUND", 1)}


def test_generation_options_rejects_non_positive_num_predict() -> None:
    with pytest.raises(ValueError, match="num_predict"):
        GenerationOptions(model="test", num_predict=0)


@pytest.mark.parametrize(
    ("format_", "version"),
    [
        ("multiple_choice", "compito-v3"),
        ("open", "compito-v3"),
        ("oral", "compito-v3"),
        ("summary", "riassunto-v2"),
    ],
)
def test_generate_uses_the_prompt_that_asks_for_delimited_formulas(
    format_: str, version: str
) -> None:
    request = GenerationRequest.model_validate({"format": format_, "count": 1})
    empty = '{"sezioni": []}' if format_ == "summary" else '{"domande": []}'
    chat = FakeChat(responses=[empty])

    result = generate(
        request=request, passages=[_doc_passage()], chat=chat, options=_options()
    )

    assert result.prompt_version == version
    assert "fra \\( e \\)" in chat.requests[0].system_prompt

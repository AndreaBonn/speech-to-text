import json

import pytest
from study_fixtures import FakeChat

from sbobina.chat_pipeline import (
    MAX_HISTORY_TURNS,
    MAX_PASSAGES,
    ChatOptions,
    ChatOutcome,
    ChatQuery,
    ChatTurn,
    answer,
    build_retrieval_question,
)
from sbobina.generation_pipeline import estimate_tokens
from sbobina.ollama_chat import CONTEXT_WINDOW_TOKENS
from sbobina.retrieval import DocumentSource, RetrievedPassage


def _passage(
    page: int = 214,
    text: str = "la causa e' illecita quando contraria a norme imperative",
) -> RetrievedPassage:
    return RetrievedPassage(
        text=text,
        source=DocumentSource(doc_id="manuale", page=page, chunk=0),
        passage_id=f"manuale:p{page}:c0",
    )


def _options(num_predict: int = 512) -> ChatOptions:
    return ChatOptions(model="test", num_predict=num_predict)


def _payload(citation_text: str, sentence: str = "La causa e' illecita.") -> str:
    return json.dumps(
        {
            "frasi": [
                {
                    "testo": sentence,
                    "citazioni": [{"passaggio": "P1", "testo": citation_text}],
                }
            ]
        }
    )


def test_answer_returns_not_found_without_calling_chat_when_no_passages() -> None:
    chat = FakeChat(responses=["should never be read"])

    result = answer(
        query=ChatQuery(question="che cos'e' la causa?"),
        passages=[],
        chat=chat,
        options=_options(),
    )

    assert result.outcome == ChatOutcome.NOT_FOUND
    assert result.sentences == ()
    assert chat.requests == []


def test_answer_keeps_sentence_with_cited_quote() -> None:
    chat = FakeChat(responses=[_payload("la causa e' illecita quando contraria")])

    result = answer(
        query=ChatQuery(question="che cos'e' la causa?"),
        passages=[_passage()],
        chat=chat,
        options=_options(),
    )

    assert result.outcome == ChatOutcome.DONE
    assert len(result.sentences) == 1
    assert result.sentences[0].citations[0].passage_id == "manuale:p214:c0"
    assert result.discarded == 0


def test_answer_discards_sentence_with_fabricated_citation_keeps_others() -> None:
    payload = json.dumps(
        {
            "frasi": [
                {
                    "testo": "scartata",
                    "citazioni": [
                        {"passaggio": "P1", "testo": "parole mai scritte nel passaggio"}
                    ],
                },
                {
                    "testo": "tenuta",
                    "citazioni": [
                        {
                            "passaggio": "P1",
                            "testo": "la causa e' illecita quando contraria",
                        }
                    ],
                },
            ]
        }
    )
    chat = FakeChat(responses=[payload])

    result = answer(
        query=ChatQuery(question="che cos'e' la causa?"),
        passages=[_passage()],
        chat=chat,
        options=_options(),
    )

    assert result.outcome == ChatOutcome.DONE
    assert [s.text for s in result.sentences] == ["tenuta"]
    assert result.discarded == 1


def test_answer_returns_not_found_when_no_sentence_survives_validation() -> None:
    chat = FakeChat(responses=[_payload("parole mai scritte nel passaggio")])

    result = answer(
        query=ChatQuery(question="che cos'e' la causa?"),
        passages=[_passage()],
        chat=chat,
        options=_options(),
    )

    assert result.outcome == ChatOutcome.NOT_FOUND
    assert result.sentences == ()
    assert result.discarded == 1


def test_answer_empty_sentence_list_is_not_found_without_discards() -> None:
    chat = FakeChat(responses=[json.dumps({"frasi": []})])

    result = answer(
        query=ChatQuery(question="che cos'e' la causa?"),
        passages=[_passage()],
        chat=chat,
        options=_options(),
    )

    assert result.outcome == ChatOutcome.NOT_FOUND
    assert result.discarded == 0


def test_answer_retries_invalid_json_then_succeeds() -> None:
    chat = FakeChat(responses=["{", _payload("la causa e' illecita quando contraria")])

    result = answer(
        query=ChatQuery(question="che cos'e' la causa?"),
        passages=[_passage()],
        chat=chat,
        options=_options(),
    )

    assert result.outcome == ChatOutcome.DONE
    assert len(chat.requests) == 2


def test_answer_fails_after_exhausting_retries_on_invalid_json() -> None:
    chat = FakeChat(responses=["{", "{"])

    result = answer(
        query=ChatQuery(question="che cos'e' la causa?"),
        passages=[_passage()],
        chat=chat,
        options=_options(),
    )

    assert result.outcome == ChatOutcome.FAILED
    assert result.error == "INVALID_RESPONSE"
    assert result.sentences == ()


def test_answer_only_last_two_exchanges_reach_the_prompt() -> None:
    history = tuple(
        ChatTurn(
            question=f"domanda numero {i}",
            sentences=(),
        )
        for i in range(10)
    )
    chat = FakeChat(responses=[_payload("la causa e' illecita quando contraria")])

    answer(
        query=ChatQuery(question="e quella attuale?", history=history),
        passages=[_passage()],
        chat=chat,
        options=_options(),
    )

    sent_message = chat.requests[0].user_message
    assert MAX_HISTORY_TURNS == 2
    for turn in history[:-MAX_HISTORY_TURNS]:
        assert turn.question not in sent_message
    for turn in history[-MAX_HISTORY_TURNS:]:
        assert turn.question in sent_message


def test_build_retrieval_question_expands_short_back_reference() -> None:
    history = (ChatTurn(question="che cos’è il possesso?", sentences=()),)

    expanded = build_retrieval_question(question="e quella di prima?", history=history)

    assert expanded == "che cos’è il possesso? e quella di prima?"


def test_build_retrieval_question_keeps_long_self_contained_question() -> None:
    history = (ChatTurn(question="che cos'e' il possesso?", sentences=()),)
    long_question = "qual e' la differenza tra possesso e detenzione nel codice civile?"

    expanded = build_retrieval_question(question=long_question, history=history)

    assert expanded == long_question


def test_build_retrieval_question_without_history_returns_question_unchanged() -> None:
    expanded = build_retrieval_question(question="e quella di prima?", history=())

    assert expanded == "e quella di prima?"


def test_prompt_stays_under_token_budget_with_max_passages_and_output_margin() -> None:
    passage_text = " ".join(f"parola{i}" for i in range(120))
    passages = [_passage(page=n, text=passage_text) for n in range(1, MAX_PASSAGES + 5)]
    options = _options(num_predict=512)
    chat = FakeChat(responses=[json.dumps({"frasi": []})])

    answer(
        query=ChatQuery(question="che cos'e' la causa?"),
        passages=passages,
        chat=chat,
        options=options,
    )

    sent = chat.requests[0]
    total = estimate_tokens(sent.system_prompt) + estimate_tokens(sent.user_message)
    assert total + options.num_predict <= CONTEXT_WINDOW_TOKENS


def test_prompt_only_includes_budgeted_passages() -> None:
    passages = [_passage(page=n) for n in range(1, MAX_PASSAGES + 5)]
    chat = FakeChat(responses=[json.dumps({"frasi": []})])

    answer(
        query=ChatQuery(question="che cos'e' la causa?"),
        passages=passages,
        chat=chat,
        options=_options(),
    )

    sent_message = chat.requests[0].user_message
    assert f"[P{MAX_PASSAGES}]" in sent_message
    assert f"[P{MAX_PASSAGES + 1}]" not in sent_message


def test_answer_not_found_history_renders_course_message() -> None:
    question = "Che cos’è la causa?"
    chat = FakeChat(responses=[json.dumps({"frasi": []}), json.dumps({"frasi": []})])
    missing = answer(
        query=ChatQuery(question=question),
        passages=[_passage()],
        chat=chat,
        options=_options(),
    )
    assert missing.outcome == ChatOutcome.NOT_FOUND

    answer(
        query=ChatQuery(
            question="E il possesso?",
            history=(ChatTurn(question=question, sentences=missing.sentences),),
        ),
        passages=[_passage()],
        chat=chat,
        options=_options(),
    )

    assert chat.requests[1].user_message.splitlines()[:3] == [
        "Domanda: Che cos’è la causa?",
        "Risposta: Non trovo la risposta nel materiale di questo corso.",
        "Domanda: E il possesso?",
    ]


def test_answer_keeps_sentence_dropping_only_its_fabricated_citation() -> None:
    # Measured (T046): the correct definition of "avviamento" was lost because
    # its second citation was invented; the first one still supports it.
    payload = json.dumps(
        {
            "frasi": [
                {
                    "testo": "La causa e' illecita.",
                    "citazioni": [
                        {"passaggio": "P1", "testo": "la causa e' illecita quando"},
                        {
                            "passaggio": "P1",
                            "testo": "parole mai scritte nel passaggio",
                        },
                    ],
                }
            ]
        }
    )

    result = answer(
        query=ChatQuery(question="che cos'e' la causa?"),
        passages=[_passage()],
        chat=FakeChat(responses=[payload]),
        options=_options(),
    )

    assert result.outcome == ChatOutcome.DONE
    assert result.discarded == 0
    [sentence] = result.sentences
    assert [c.quote for c in sentence.citations] == ["la causa e' illecita quando"]


def test_build_retrieval_question_blank_question_reuses_previous_one_stripped() -> None:
    history = (ChatTurn(question="che cos'e' il possesso?", sentences=()),)

    assert build_retrieval_question(question="  ", history=history) == (
        "che cos'e' il possesso?"
    )


def test_chat_options_rejects_non_positive_num_predict() -> None:
    with pytest.raises(ValueError, match="num_predict"):
        ChatOptions(model="test", num_predict=0)

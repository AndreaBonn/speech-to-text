import json

import pytest
from study_fixtures import FakeChat

from sbobina.generation_models import GenerationRequest
from sbobina.generation_pipeline import (
    GenerationOptions,
    GenerationOutcome,
    complete_questions,
    generate,
)
from sbobina.retrieval import DocumentSource, RetrievedPassage

QUOTE = "la presunzione parte da un fatto noto per giungere a un fatto ignoto"


def _passage() -> RetrievedPassage:
    return RetrievedPassage(
        text=f"ora {QUOTE} secondo il codice",
        source=DocumentSource(doc_id="manuale", page=12, chunk=0),
        passage_id="manuale:p12:c0",
    )


def _question(number: int) -> dict[str, object]:
    return {
        "domanda": f"Domanda {number} sulla presunzione?",
        "soluzione": "Parte da un fatto noto.",
        "citazioni": [{"passaggio": "P1", "testo": QUOTE}],
    }


def _cut_reply(complete: int) -> str:
    """A reply cut by the token limit inside the question after `complete`."""
    whole = json.dumps({"domande": [_question(n) for n in range(complete + 1)]})
    return whole[: whole.rindex('"soluzione"')]


def test_complete_questions_returns_only_the_questions_written_in_full() -> None:
    assert complete_questions(content=_cut_reply(complete=2)) == [
        _question(0),
        _question(1),
    ]


def test_complete_questions_of_a_reply_without_questions_is_empty() -> None:
    assert complete_questions(content='{"domande": [{"domanda": "a') == []
    assert complete_questions(content="non json") == []


def test_generate_keeps_the_requested_questions_of_a_reply_cut_after_them() -> None:
    # F40: asked for 1 oral question, qwen wrote more and hit num_predict in
    # the second one; both attempts came back the same and the exam failed.
    request = GenerationRequest.model_validate({"format": "oral", "count": 1})
    chat = FakeChat(responses=[_cut_reply(complete=1)])

    result = generate(
        request=request,
        passages=[_passage()],
        chat=chat,
        options=GenerationOptions(model="test"),
    )

    assert result.outcome is GenerationOutcome.DONE
    assert [q.question for q in result.questions] == ["Domanda 0 sulla presunzione?"]
    assert len(chat.requests) == 1


def test_generate_keeps_fewer_questions_than_asked_from_a_cut_reply() -> None:
    # Measured on "possesso" (3 open questions, 856 tokens): the cut fell in
    # the third question with v3 and v4 alike, and the retry was identical.
    request = GenerationRequest.model_validate({"format": "open", "count": 3})
    chat = FakeChat(responses=[_cut_reply(complete=2)])

    result = generate(
        request=request,
        passages=[_passage()],
        chat=chat,
        options=GenerationOptions(model="test"),
    )

    assert result.outcome is GenerationOutcome.DONE
    assert len(result.questions) == 2


def test_generate_still_fails_when_the_cut_reply_has_no_complete_question() -> None:
    request = GenerationRequest.model_validate({"format": "oral", "count": 3})
    chat = FakeChat(responses=[_cut_reply(complete=0)])

    result = generate(
        request=request,
        passages=[_passage()],
        chat=chat,
        options=GenerationOptions(model="test"),
    )

    assert result.outcome is GenerationOutcome.FAILED
    assert len(chat.requests) == 2


def test_complete_questions_reads_the_array_of_the_domande_key() -> None:
    # Prose before the JSON may quote the word "domande" (F82).
    content = 'Ecco le "domande" [richieste]:\n' + _cut_reply(complete=1)

    assert complete_questions(content=content) == [_question(0)]


def test_generate_logs_an_unreadable_reply_it_could_not_salvage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A25: the record only says INVALID_RESPONSE; the log keeps the reply.
    caplog.set_level("WARNING", logger="sbobina")
    request = GenerationRequest.model_validate({"format": "oral", "count": 1})
    chat = FakeChat(responses=["testo che non è JSON"])

    generate(
        request=request,
        passages=[_passage()],
        chat=chat,
        options=GenerationOptions(model="test"),
    )

    assert "testo che non è JSON" in caplog.text


def test_generate_does_not_log_a_readable_reply(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING", logger="sbobina")
    request = GenerationRequest.model_validate({"format": "oral", "count": 1})
    chat = FakeChat(responses=[json.dumps({"domande": [_question(0)]})])

    generate(
        request=request,
        passages=[_passage()],
        chat=chat,
        options=GenerationOptions(model="test"),
    )

    assert caplog.text == ""


def _summary_reply() -> str:
    sentence = {
        "testo": "Parte da un fatto noto.",
        "citazioni": [{"passaggio": "P1", "testo": QUOTE}],
    }
    return json.dumps({"sezioni": [{"titolo": "Presunzione", "frasi": [sentence]}]})


def test_generate_retries_a_summary_whose_reply_is_unreadable() -> None:
    # Measured on a real slide: a summary cut by num_predict crashed the
    # generation (KeyError in the question salvage) instead of retrying.
    request = GenerationRequest.model_validate({"format": "summary", "count": 1})
    chat = FakeChat(responses=[_summary_reply()[:-5], _summary_reply()])

    result = generate(
        request=request,
        passages=[_passage()],
        chat=chat,
        options=GenerationOptions(model="test"),
    )

    assert result.outcome is GenerationOutcome.DONE
    assert len(result.sections) == 1
    assert len(chat.requests) == 2


def _section(number: int) -> dict[str, object]:
    return {
        "titolo": f"Sezione {number}",
        "frasi": [
            {
                "testo": "Parte da un fatto noto.",
                "citazioni": [{"passaggio": "P1", "testo": QUOTE}],
            }
        ],
    }


def _cut_summary(complete: int) -> str:
    """A summary cut by the token limit inside the section after `complete`."""
    whole = json.dumps({"sezioni": [_section(n) for n in range(complete + 1)]})
    return whole[: whole.rindex('"frasi"')]


def test_generate_keeps_the_complete_sections_of_a_cut_summary() -> None:
    # Measured on a real slide (page 4): the reply broke inside the fourth
    # section at both attempts (an unescaped '"' in a quote), after three
    # whole sections, and the generation failed.
    request = GenerationRequest.model_validate({"format": "summary", "count": 1})
    chat = FakeChat(responses=[_cut_summary(complete=2)])

    result = generate(
        request=request,
        passages=[_passage()],
        chat=chat,
        options=GenerationOptions(model="test"),
    )

    assert result.outcome is GenerationOutcome.DONE
    assert [s.title for s in result.sections] == ["Sezione 0", "Sezione 1"]
    assert len(chat.requests) == 1


def test_generate_keeps_the_sections_before_an_unescaped_quote() -> None:
    whole = json.dumps({"sezioni": [_section(n) for n in range(3)]})
    broken = whole.replace('"titolo": "Sezione 2"', '"titolo": "Il "miglior" stato"', 1)
    chat = FakeChat(responses=[broken])

    result = generate(
        request=GenerationRequest.model_validate({"format": "summary", "count": 1}),
        passages=[_passage()],
        chat=chat,
        options=GenerationOptions(model="test"),
    )

    assert [s.title for s in result.sections] == ["Sezione 0", "Sezione 1"]

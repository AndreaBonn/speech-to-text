import json

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


def test_generate_still_fails_when_the_cut_reply_lacks_requested_questions() -> None:
    request = GenerationRequest.model_validate({"format": "oral", "count": 3})
    chat = FakeChat(responses=[_cut_reply(complete=1)])

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

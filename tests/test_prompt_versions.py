import json

import pytest
from study_fixtures import FakeChat, response_fixture, transcript_fixture

from sbobina.chat_pipeline import ChatOptions, ChatQuery, answer
from sbobina.generation_models import GenerationRequest
from sbobina.generation_pipeline import GenerationOptions, generate
from sbobina.retrieval import DocumentSource, RetrievedPassage
from sbobina.study_pipeline import StudyOptions, generate_study

FORMULA_RULE = "fra \\( e \\)"


def _passage() -> RetrievedPassage:
    return RetrievedPassage(
        text="la causa e' illecita quando contraria a norme imperative",
        source=DocumentSource(doc_id="manuale", page=214, chunk=0),
        passage_id="manuale:p214:c0",
    )


@pytest.mark.parametrize(
    ("format_", "version"),
    [
        ("multiple_choice", "compito-v4"),
        ("open", "compito-v4"),
        ("oral", "compito-v4"),
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
        request=request,
        passages=[_passage()],
        chat=chat,
        options=GenerationOptions(model="test"),
    )

    assert result.prompt_version == version
    assert FORMULA_RULE in chat.requests[0].system_prompt


def test_answer_uses_the_prompt_that_asks_for_delimited_formulas() -> None:
    chat = FakeChat(responses=[json.dumps({"frasi": []})])

    answer(
        query=ChatQuery(question="che cos'e' la velocita'?"),
        passages=[_passage()],
        chat=chat,
        options=ChatOptions(model="test"),
    )

    assert FORMULA_RULE in chat.requests[0].system_prompt


def test_generate_study_records_the_prompt_that_asks_for_delimited_formulas() -> None:
    chat = FakeChat(responses=[response_fixture()])

    result = generate_study(
        transcript=transcript_fixture(), chat=chat, options=StudyOptions(model="test")
    )

    assert result.prompt_version == "studio-v2"
    assert FORMULA_RULE in chat.requests[0].system_prompt

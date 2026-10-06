import json
from typing import cast

import ollama
import pytest

from sbobina.ollama_chat import ChatRequest, chat_json, escape_inner_quotes

# The real reply (page 4 of a macroeconomics slide deck, 2026-10-06): qwen
# copied a slide line with its quotes into a citation, at both attempts.
REAL_CITATION = (
    '{"testo": "Il "miglior" stato stazionario è quello con il più elevato '
    'consumo pro capite", "passaggio": "P8"}'
)


class FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content

    def chat(self, **kwargs: object) -> ollama.ChatResponse:
        return ollama.ChatResponse(
            message=ollama.Message(role="assistant", content=self.content)
        )


def _request() -> ChatRequest:
    return ChatRequest(
        model="local-model", system_prompt="system", user_message="user", schema={}
    )


def test_escape_inner_quotes_keeps_the_quoted_word_of_a_real_citation() -> None:
    repaired = json.loads(escape_inner_quotes(content=REAL_CITATION))

    assert repaired["testo"].startswith('Il "miglior" stato stazionario')
    assert repaired["passaggio"] == "P8"


@pytest.mark.parametrize(
    ("content", "text"),
    [
        ('{"t": "detto "x", poi y"}', 'detto "x", poi y'),
        ('{"t": "fine "citata"."}', 'fine "citata".'),
        ('["a "b" c", "d"]', 'a "b" c'),
    ],
)
def test_escape_inner_quotes_escapes_quotes_that_do_not_close_a_string(
    content: str, text: str
) -> None:
    parsed = json.loads(escape_inner_quotes(content=content))

    assert (parsed["t"] if isinstance(parsed, dict) else parsed[0]) == text


def test_chat_json_repairs_unescaped_quotes_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING", logger="sbobina")

    content = chat_json(
        client=cast(ollama.Client, FakeClient(content=REAL_CITATION)),
        request=_request(),
    )

    assert json.loads(content)["passaggio"] == "P8"
    assert "virgolette" in caplog.text


def test_chat_json_leaves_a_valid_reply_with_escaped_quotes_unchanged() -> None:
    valid = json.dumps({"testo": 'Il "miglior" stato', "punti": ["a, b", "c"]})

    assert (
        chat_json(
            client=cast(ollama.Client, FakeClient(content=valid)), request=_request()
        )
        == valid
    )


def test_chat_json_leaves_a_reply_the_repair_cannot_parse_as_is() -> None:
    # A quote followed by ":" looks like the end of a key: no safe repair.
    broken = '{"testo": "nota "importante": vedi sopra"}'

    assert (
        chat_json(
            client=cast(ollama.Client, FakeClient(content=broken)), request=_request()
        )
        == broken
    )


def test_escape_inner_quotes_gives_up_rather_than_splitting_a_list_item() -> None:
    # Code review: '", "' inside one item reads like an item boundary, and a
    # repair would turn one judge point into two without any error.
    content = '["Il "punto", "secondo" critico"]'

    assert escape_inner_quotes(content=content) == content

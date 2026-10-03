"""Model output and document text reach the page as data, never as markup (A8)."""

import json
import re
from pathlib import Path

import pytest
from chat_api_fixtures import ChatApp, chat_app
from study_fixtures import QUOTE

from sbobina.ollama_chat import ChatRequest

__all__ = ["chat_app"]

MARKUP = '<img src=x onerror="window.__xss=1"><script>window.__xss=2</script>'
SCRIPTS_DIR = Path(__file__).parents[2] / "src" / "sbobina" / "web" / "static" / "js"
# Scripts that render text from the model, from documents or from the user.
UNTRUSTED_TEXT_SCRIPTS = (
    "corso-chat.js",
    "corso-chat-thread.js",
    "corso-generazioni.js",
    "corso-generazioni-dettaglio.js",
    "corso-generazioni-azioni.js",
    "corso-generazioni-form.js",
    "corso-materiali.js",
    "corso-ocr.js",
    "documento.js",
    "studio.js",
)
HTML_SINK = re.compile(r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write")


def _markup_answer(request: ChatRequest) -> str:
    sentence = {
        "testo": f"{MARKUP} La causa è illecita.",
        "citazioni": [{"passaggio": "P1", "testo": QUOTE}],
    }
    return json.dumps({"frasi": [sentence]})


def test_chat_answer_with_markup_is_returned_verbatim_as_json(
    chat_app: ChatApp,
) -> None:
    chat_app.model.behaviour = _markup_answer
    chat_id = chat_app.new_chat()

    response = chat_app.ask(chat_id=chat_id)

    assert response.headers["content-type"].startswith("application/json")
    text = response.json()["data"]["sentences"][0]["text"]
    assert text == f"{MARKUP} La causa è illecita."
    detail = chat_app.client.get(f"/api/v1/courses/diritto/chats/{chat_id}")
    stored = detail.json()["data"]["messages"][1]["sentences"][0]["text"]
    assert stored == text


def test_html_sink_pattern_catches_markup_assignment() -> None:
    # Positive control: without it the guard below could pass on any input.
    assert HTML_SINK.search("row.innerHTML = answer.text;")
    assert HTML_SINK.search("el.insertAdjacentHTML('beforeend', html)")
    assert not HTML_SINK.search("// never innerHTML: see dom.js")


@pytest.mark.parametrize("name", UNTRUSTED_TEXT_SCRIPTS)
def test_untrusted_text_scripts_never_write_markup(name: str) -> None:
    source = (SCRIPTS_DIR / name).read_text(encoding="utf-8")

    assert HTML_SINK.search(source) is None

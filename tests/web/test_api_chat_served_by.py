from typing import Any, cast

from chat_api_fixtures import CHATS_URL, ChatApp, chat_app

from sbobina.llm_chain import ChainLink, FallbackChain
from sbobina.llm_errors import FailureKind, ProviderUnavailableError
from sbobina.ollama_chat import ChatRequest
from sbobina.web.chat_records import ChatAnswerRecord, line_to_record, record_to_line

__all__ = ["chat_app"]


def _rate_limited(request: ChatRequest) -> str:
    raise ProviderUnavailableError(
        kind=FailureKind.RATE_LIMIT, provider="groq/llama-x", retry_after_s=None
    )


def _use_chain(chat_app: ChatApp) -> None:
    chain = FallbackChain(
        links=[
            ChainLink(provider="groq", model="llama-x", client=_rate_limited),
            ChainLink(provider="ollama", model="qwen", client=chat_app.model),
        ]
    )
    cast(Any, chat_app.client.app).state.chat_client = chain


def test_answer_says_which_link_served_it_and_keeps_it_on_reload(
    chat_app: ChatApp,
) -> None:
    _use_chain(chat_app=chat_app)
    chat_id = chat_app.new_chat()

    data = chat_app.ask(chat_id=chat_id).json()["data"]

    assert data["served_by"] == {"ollama/qwen": 1}
    detail = chat_app.client.get(f"{CHATS_URL}/{chat_id}").json()["data"]
    assert detail["messages"][-1]["served_by"] == {"ollama/qwen": 1}


def test_each_turn_counts_only_its_own_calls(chat_app: ChatApp) -> None:
    _use_chain(chat_app=chat_app)
    chat_id = chat_app.new_chat()

    chat_app.ask(chat_id=chat_id)
    second = chat_app.ask(chat_id=chat_id).json()["data"]

    assert second["served_by"] == {"ollama/qwen": 1}


def test_answer_from_a_plain_client_has_no_served_by(chat_app: ChatApp) -> None:
    chat_id = chat_app.new_chat()

    data = chat_app.ask(chat_id=chat_id).json()["data"]

    assert data["outcome"] == "DONE"
    assert data["served_by"] is None


def test_answer_line_written_before_served_by_still_loads() -> None:
    old_line = {
        "kind": "answer",
        "question_id": "q1",
        "outcome": "DONE",
        "sentences": [],
        "discarded": 0,
        "error": None,
        "created_at": "2026-10-01T10:00:00+00:00",
    }

    record = line_to_record(raw=old_line)

    assert isinstance(record, ChatAnswerRecord)
    assert record.served_by is None
    assert "served_by" not in record_to_line(record=record)

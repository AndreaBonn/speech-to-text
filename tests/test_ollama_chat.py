from typing import cast

import httpx
import ollama
import pytest

from sbobina.correction import CorrectorUnavailableError, InvalidResponseError
from sbobina.ollama_chat import ChatRequest, chat_json, close_open_brackets


class FakeClient:
    def __init__(self, content: str | None = None, error: Exception | None = None):
        self.content = content
        self.error = error
        self.arguments: dict[str, object] = {}

    def chat(self, **kwargs: object) -> ollama.ChatResponse:
        self.arguments = kwargs
        if self.error is not None:
            raise self.error
        return ollama.ChatResponse(
            message=ollama.Message(role="assistant", content=self.content)
        )


def request() -> ChatRequest:
    return ChatRequest(
        model="local-model",
        system_prompt="system",
        user_message="user",
        schema={"type": "object"},
    )


@pytest.mark.parametrize(
    "content", ['{"ok": true}', '```json\n{"ok": true}\n```', '```\n{"ok": true}\n```']
)
def test_chat_json_returns_unfenced_content_and_preserves_options(content: str) -> None:
    client = FakeClient(content=content)
    assert (
        chat_json(client=cast(ollama.Client, client), request=request())
        == '{"ok": true}'
    )
    assert client.arguments == {
        "model": "local-model",
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "user"},
        ],
        "format": {"type": "object"},
        "think": False,
        "options": {"temperature": 0, "num_ctx": 8192},
    }


@pytest.mark.parametrize(
    "error",
    [
        ollama.ResponseError("missing", status_code=404),
        httpx.ReadError("reset"),
        ConnectionError("down"),
    ],
)
def test_chat_json_maps_unavailable_errors_preserving_cause(error: Exception) -> None:
    with pytest.raises(CorrectorUnavailableError) as raised:
        chat_json(
            client=cast(ollama.Client, FakeClient(error=error)), request=request()
        )
    assert raised.value.__cause__ is error


def test_chat_json_maps_invalid_body_preserving_cause() -> None:
    error = ValueError("truncated response")
    with pytest.raises(InvalidResponseError) as raised:
        chat_json(
            client=cast(ollama.Client, FakeClient(error=error)), request=request()
        )
    assert raised.value.__cause__ is error


def test_chat_json_leaves_content_validation_to_the_caller() -> None:
    assert (
        chat_json(
            client=cast(ollama.Client, FakeClient(content=None)), request=request()
        )
        == ""
    )
    assert (
        chat_json(
            client=cast(ollama.Client, FakeClient(content="not JSON")),
            request=request(),
        )
        == "not JSON"
    )


def test_chat_json_forwards_study_output_limit() -> None:
    from dataclasses import replace

    client = FakeClient(content='{"capitoli": []}')
    chat_json(
        client=cast(ollama.Client, client), request=replace(request(), num_predict=321)
    )
    assert client.arguments["options"] == {
        "temperature": 0,
        "num_ctx": 8192,
        "num_predict": 321,
    }


class CountingClient:
    def __init__(self, done_reason: str) -> None:
        self.done_reason = done_reason

    def chat(self, **kwargs: object) -> ollama.ChatResponse:
        return ollama.ChatResponse(
            message=ollama.Message(role="assistant", content="{}"),
            prompt_eval_count=5000,
            eval_count=900,
            done_reason=self.done_reason,
        )


def test_chat_json_logs_token_counts(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger="sbobina")

    chat_json(client=cast(ollama.Client, CountingClient("stop")), request=request())

    assert "prompt_tokens=5000" in caplog.text
    assert "output_tokens=900" in caplog.text
    assert not [r for r in caplog.records if r.levelname == "WARNING"]


def test_chat_json_warns_when_output_hits_the_limit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO", logger="sbobina")

    chat_json(client=cast(ollama.Client, CountingClient("length")), request=request())

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "troncata" in warnings[0].getMessage()


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"a": [{"b": 1}]', '{"a": [{"b": 1}]}'),
        ('{"a": [{"b": "x}"}', '{"a": [{"b": "x}"}]}'),
        ('{"a": "va\\"le"', '{"a": "va\\"le"}'),
        ('{"a": 1}', '{"a": 1}'),
    ],
)
def test_close_open_brackets_appends_missing_closers(
    content: str, expected: str
) -> None:
    assert close_open_brackets(content=content) == expected


@pytest.mark.parametrize(
    "content",
    ['{"a": "cut in the mid', '{"a": [1}', '{"a": 1}}', "not json"],
)
def test_close_open_brackets_leaves_unrepairable_content_alone(content: str) -> None:
    assert close_open_brackets(content=content) == content


def test_chat_json_repairs_a_reply_missing_its_last_brace(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO", logger="sbobina")
    client = FakeClient(content='{"sezioni": [{"titolo": "t", "frasi": []}]')

    content = chat_json(client=cast(ollama.Client, client), request=request())

    assert content == '{"sezioni": [{"titolo": "t", "frasi": []}]}'
    assert "chiuse" in caplog.text


class TruncatedClient:
    def chat(self, **kwargs: object) -> ollama.ChatResponse:
        return ollama.ChatResponse(
            message=ollama.Message(role="assistant", content='{"a": [{"x": 1}'),
            done_reason="length",
        )


def test_chat_json_leaves_a_truncated_reply_unrepaired() -> None:
    # Closing a reply cut by num_predict would accept a partial list as
    # complete and skip the caller's retry: only a reply that stopped on its
    # own gets its missing closers.
    content = chat_json(
        client=cast(ollama.Client, TruncatedClient()), request=request()
    )

    assert content == '{"a": [{"x": 1}'

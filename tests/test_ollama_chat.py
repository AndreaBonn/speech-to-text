from typing import cast

import httpx
import ollama
import pytest

from sbobina.correction import CorrectorUnavailableError, InvalidResponseError
from sbobina.ollama_chat import ChatRequest, chat_json


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

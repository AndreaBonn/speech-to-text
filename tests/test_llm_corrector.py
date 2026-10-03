import json
import logging

import httpx
import ollama
import pytest

from sbobina.correction import CorrectorUnavailableError, Edit, InvalidResponseError
from sbobina.llm_corrector import (
    ModelDownloadError,
    build_system_prompt,
    build_user_message,
    ensure_model,
    make_ollama_corrector,
    parse_response,
)
from sbobina.notices import USER_NOTICE

ANSWER_WITH_ONE_EDIT = (
    '{"correzioni": [{"originale": "legione", "corretto": "lesione"}]}'
)


def test_parse_response_maps_italian_keys_to_edits() -> None:
    content = '{"correzioni": [{"originale": "legione", "corretto": "lesione"}]}'

    assert parse_response(content) == [Edit(original="legione", corrected="lesione")]


def test_parse_response_empty_list_is_valid() -> None:
    assert parse_response('{"correzioni": []}') == []


def test_parse_response_malformed_json_raises_invalid_response() -> None:
    with pytest.raises(InvalidResponseError):
        parse_response('{"correzioni": [{"originale": "x"}]')


def test_build_system_prompt_includes_subject_when_given() -> None:
    prompt = build_system_prompt("diritto privato")

    assert "Materia della lezione: diritto privato." in prompt
    assert "{materia}" not in prompt


def test_build_system_prompt_without_subject_leaves_no_placeholder() -> None:
    prompt = build_system_prompt(None)

    assert "{materia}" not in prompt
    assert "Materia della lezione" not in prompt


def test_build_user_message_marks_start_of_lecture_without_context() -> None:
    message = build_user_message("testo", "")

    assert "(inizio della lezione)" in message
    assert message.endswith("Testo da correggere:\ntesto")


def test_parse_response_accepts_json_inside_markdown_fence() -> None:
    content = (
        '```json\n{"correzioni": [{"originale": "esinto", "corretto": "estinto"}]}\n```'
    )

    assert parse_response(content) == [Edit(original="esinto", corrected="estinto")]


def test_parse_response_fenced_but_off_schema_raises_invalid_response() -> None:
    with pytest.raises(InvalidResponseError):
        parse_response('```json\n{"risultato": 4}\n```')


def test_ollama_corrector_translates_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DownClient:
        def __init__(self, host: str) -> None:
            pass

        def chat(self, **kwargs: object) -> object:
            raise ConnectionError("Failed to connect to Ollama")

    monkeypatch.setattr(ollama, "Client", DownClient)
    corrector = make_ollama_corrector(model="m", host="http://x", subject=None)

    with pytest.raises(CorrectorUnavailableError):
        corrector("testo", "")


def test_ollama_corrector_truncated_body_is_an_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class GarbledClient:
        def __init__(self, host: str) -> None:
            pass

        def chat(self, **kwargs: object) -> object:
            raise json.JSONDecodeError("Expecting value", doc="", pos=0)

    monkeypatch.setattr(ollama, "Client", GarbledClient)
    corrector = make_ollama_corrector(model="m", host="http://x", subject=None)

    with pytest.raises(InvalidResponseError):
        corrector("testo", "")


class _FakeOllama:
    """Ollama client double: ``installed`` models answer ``show``, the rest 404."""

    def __init__(self, installed: set[str], pull_error: Exception | None = None):
        self.installed = installed
        self.pull_error = pull_error
        self.pulled: list[str] = []

    def __call__(self, host: str) -> "_FakeOllama":
        return self

    def show(self, model: str) -> object:
        if model not in self.installed:
            raise ollama.ResponseError(f"model '{model}' not found", status_code=404)
        return object()

    def pull(self, model: str) -> object:
        if self.pull_error is not None:
            raise self.pull_error
        self.pulled.append(model)
        self.installed.add(model)
        return object()


def test_ensure_model_installed_does_not_pull(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeOllama(installed={"qwen3.5:9b"})
    monkeypatch.setattr(ollama, "Client", fake)

    pulled = ensure_model(model="qwen3.5:9b", host="http://x")

    assert pulled is False
    assert fake.pulled == []


def test_ensure_model_missing_pulls_and_tells_the_user(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake = _FakeOllama(installed=set())
    monkeypatch.setattr(ollama, "Client", fake)

    with caplog.at_level(logging.INFO, logger="sbobina"):
        pulled = ensure_model(model="qwen3.5:4b", host="http://x")

    assert pulled is True
    assert fake.pulled == ["qwen3.5:4b"]
    notices = [r for r in caplog.records if getattr(r, USER_NOTICE, False)]
    assert [r.getMessage() for r in notices] == [
        (
            "Scarico il modello Ollama qwen3.5:4b: la prima volta può richiedere "
            "diversi minuti"
        )
    ]


def test_ensure_model_unreachable_server_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DownClient:
        def __init__(self, host: str) -> None:
            pass

        def show(self, model: str) -> object:
            raise ConnectionError("Failed to connect to Ollama")

    monkeypatch.setattr(ollama, "Client", DownClient)

    with pytest.raises(CorrectorUnavailableError):
        ensure_model(model="qwen3.5:9b", host="http://x")


def test_ensure_model_unknown_name_raises_with_the_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = ollama.ResponseError("pull model manifest: file does not exist")
    monkeypatch.setattr(
        ollama, "Client", _FakeOllama(installed=set(), pull_error=error)
    )

    with pytest.raises(ModelDownloadError, match="qwnn:9b"):
        ensure_model(model="qwnn:9b", host="http://x")


class _AnsweringClient:
    """Ollama client double whose ``chat`` returns a fixed message content."""

    content: str | None = None

    def __init__(self, host: str) -> None:
        pass

    def chat(self, **kwargs: object) -> ollama.ChatResponse:
        return ollama.ChatResponse(
            message=ollama.Message(role="assistant", content=self.content)
        )


def test_ollama_corrector_returns_edits_from_the_model_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_AnsweringClient, "content", ANSWER_WITH_ONE_EDIT)
    monkeypatch.setattr(ollama, "Client", _AnsweringClient)
    corrector = make_ollama_corrector(model="m", host="http://x", subject=None)

    assert corrector("la legione", "") == [
        Edit(original="legione", corrected="lesione")
    ]


def test_ollama_corrector_empty_message_is_an_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_AnsweringClient, "content", None)
    monkeypatch.setattr(ollama, "Client", _AnsweringClient)
    corrector = make_ollama_corrector(model="m", host="http://x", subject=None)

    with pytest.raises(InvalidResponseError):
        corrector("la legione", "")


def test_ensure_model_server_error_on_lookup_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingClient:
        def __init__(self, host: str) -> None:
            pass

        def show(self, model: str) -> object:
            raise ollama.ResponseError("internal error", status_code=500)

    monkeypatch.setattr(ollama, "Client", FailingClient)

    with pytest.raises(CorrectorUnavailableError, match="internal error"):
        ensure_model(model="qwen3.5:9b", host="http://x")


def test_ensure_model_connection_lost_during_pull_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = httpx.ReadError("connection reset")
    monkeypatch.setattr(
        ollama, "Client", _FakeOllama(installed=set(), pull_error=error)
    )

    with pytest.raises(CorrectorUnavailableError, match="connection reset"):
        ensure_model(model="qwen3.5:9b", host="http://x")


def test_build_user_message_puts_previous_paragraph_before_the_text() -> None:
    message = build_user_message("ha esinto il credito", "la lesione degli interessi")

    assert message == (
        "Paragrafo precedente, solo come contesto (non correggerlo):\n"
        "la lesione degli interessi\n\n"
        "Testo da correggere:\nha esinto il credito"
    )

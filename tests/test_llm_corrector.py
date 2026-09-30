import json

import ollama
import pytest

from sbobina.correction import CorrectorUnavailableError, Edit, InvalidResponseError
from sbobina.llm_corrector import (
    build_system_prompt,
    build_user_message,
    make_ollama_corrector,
    parse_response,
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

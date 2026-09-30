from sbobina.correction import Edit
from sbobina.llm_corrector import (
    build_system_prompt,
    build_user_message,
    parse_response,
)


def test_parse_response_maps_italian_keys_to_edits() -> None:
    content = '{"correzioni": [{"originale": "legione", "corretto": "lesione"}]}'

    assert parse_response(content) == [Edit(original="legione", corrected="lesione")]


def test_parse_response_empty_list_is_valid() -> None:
    assert parse_response('{"correzioni": []}') == []


def test_parse_response_malformed_json_returns_no_edits() -> None:
    assert parse_response('{"correzioni": [{"originale": "x"}]') == []


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


def test_parse_response_fenced_but_off_schema_returns_no_edits() -> None:
    assert parse_response('```json\n{"risultato": 4}\n```') == []

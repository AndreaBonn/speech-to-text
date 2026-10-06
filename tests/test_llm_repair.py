import json

import pytest

from sbobina.llm_repair import (
    close_open_brackets,
    escape_inner_quotes,
    escape_latex_backslashes,
    repair_json_reply,
    strip_markdown_fence,
)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"ok": true}', '{"ok": true}'),
        ('```json\n{"ok": true}\n```', '{"ok": true}'),
        ('```\n{"ok": true}\n```', '{"ok": true}'),
    ],
)
def test_strip_markdown_fence_removes_fence_when_present(
    content: str, expected: str
) -> None:
    assert strip_markdown_fence(content=content) == expected


def test_strip_markdown_fence_leaves_unfenced_content_alone() -> None:
    assert strip_markdown_fence(content="not fenced") == "not fenced"


@pytest.mark.parametrize(
    ("written", "meant"),
    [
        ("\\(x^2\\)", "\\(x^2\\)"),
        ("\\lim_{h \\to 0}", "\\lim_{h \\to 0}"),
    ],
)
def test_escape_latex_backslashes_keeps_single_backslash_latex(
    written: str, meant: str
) -> None:
    content = '{"testo": "' + written + '"}'

    repaired = escape_latex_backslashes(content=content)

    assert json.loads(repaired) == {"testo": meant}


def test_escape_latex_backslashes_leaves_valid_json_escapes_alone() -> None:
    content = '{"testo": "riga\\n e\\t fine"}'

    assert escape_latex_backslashes(content=content) == content


def test_escape_inner_quotes_escapes_a_copied_citation() -> None:
    content = '{"t": "detto "x", poi y"}'

    parsed = json.loads(escape_inner_quotes(content=content))

    assert parsed["t"] == 'detto "x", poi y'


def test_escape_inner_quotes_gives_up_on_a_list_item_boundary() -> None:
    content = '["Il "punto", "secondo" critico"]'

    assert escape_inner_quotes(content=content) == content


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"a": [{"b": 1}]', '{"a": [{"b": 1}]}'),
        ('{"a": 1}', '{"a": 1}'),
    ],
)
def test_close_open_brackets_appends_missing_closers(
    content: str, expected: str
) -> None:
    assert close_open_brackets(content=content) == expected


def test_close_open_brackets_leaves_a_cut_string_alone() -> None:
    content = '{"a": "cut in the mid'

    assert close_open_brackets(content=content) == content


def test_repair_json_reply_strips_fence_and_keeps_valid_json() -> None:
    raw = '```json\n{"ok": true}\n```'

    assert repair_json_reply(raw=raw, truncated=False) == '{"ok": true}'


def test_repair_json_reply_closes_missing_closers_on_a_complete_reply() -> None:
    raw = '{"sezioni": [{"titolo": "t", "frasi": []}]'

    repaired = repair_json_reply(raw=raw, truncated=False)

    assert repaired == '{"sezioni": [{"titolo": "t", "frasi": []}]}'
    assert json.loads(repaired)["sezioni"][0]["titolo"] == "t"


def test_repair_json_reply_leaves_a_truncated_reply_unclosed() -> None:
    raw = '{"a": [{"x": 1}'

    assert repair_json_reply(raw=raw, truncated=True) == raw


def test_repair_json_reply_escapes_latex_before_closing_brackets() -> None:
    raw = '{"frasi": [{"testo": "vale \\(\\frac{a}{b}\\)"}]}'

    repaired = repair_json_reply(raw=raw, truncated=False)

    assert json.loads(repaired) == {"frasi": [{"testo": "vale \\(\\frac{a}{b}\\)"}]}


def test_repair_json_reply_repairs_unescaped_quotes_when_brackets_alone_fail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING", logger="sbobina")
    raw = '{"testo": "Il "miglior" stato", "passaggio": "P8"}'

    repaired = repair_json_reply(raw=raw, truncated=False)

    assert json.loads(repaired)["passaggio"] == "P8"
    assert "virgolette" in caplog.text


def test_repair_json_reply_gives_up_when_no_repair_parses() -> None:
    # A quote followed by ":" looks like the end of a key: no safe repair.
    raw = '{"testo": "nota "importante": vedi sopra"}'

    assert repair_json_reply(raw=raw, truncated=False) == raw


def test_repair_json_reply_warns_once_when_closing_brackets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING", logger="sbobina")

    repair_json_reply(raw='{"a": 1}', truncated=False)

    assert not [r for r in caplog.records if r.levelname == "WARNING"]

import random
import sqlite3
import string
from contextlib import closing
from dataclasses import replace

import pytest
from conftest import make_segment, make_transcript, make_word

from sbobina.models import Segment
from sbobina.search_text import (
    MATCH_END,
    MATCH_START,
    Passage,
    SnippetPart,
    build_match_query,
    passages_from_transcript,
    snippet_parts,
)


def test_passages_from_transcript_preserves_segment_indices_and_times() -> None:
    transcript = make_transcript(
        [
            Segment(start=0.0, end=1.0, words=()),
            make_segment(words=[make_word(text=" contratto ", start=2472.0)]),
            make_segment(words=[make_word(text="  ", start=2473.0)]),
        ]
    )
    assert passages_from_transcript(transcript=transcript) == [
        Passage(segment_index=1, start=2472.0, text="contratto")
    ]
    assert passages_from_transcript(transcript=replace(transcript, segments=())) == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("contratti causa", '"contratt"* "caus"*'),
        ("di", '"di"*'),
        ('"causa illecita" x', '"causa illecita"'),
        ('"a b"', '"a b"'),
        ('"causa ""illecita"""', '"causa ""illecita"""'),
        ("NEAR(a b)", '"NEAR"*'),
        ("col:val", '"col"* "val"*'),
        ("-x", None),
        ("*", None),
        ('"', None),
        ('"***"', None),
        ("", None),
        ("  ", None),
        ("aiuoe", None),
        ("PERCHÉ", '"PERCH"*'),
    ],
)
def test_build_match_query_normalizes_words_and_quotes(
    raw: str, expected: str | None
) -> None:
    assert build_match_query(raw=raw) == expected


def test_build_match_query_limits_to_ten_usable_terms() -> None:
    assert build_match_query(raw="x " + "di " * 12) == " ".join(['"di"*'] * 10)


def symbol_queries() -> list[str]:
    generator = random.Random(20261002)
    alphabet = string.punctuation + string.ascii_letters + " èà中\x00\ue000\ue001"
    return [
        "".join(generator.choices(population=alphabet, k=generator.randrange(100)))
        for _ in range(200)
    ]


@pytest.mark.parametrize(
    "raw",
    [
        "NEAR(a b)",
        "col:val",
        "-x",
        "*",
        '"',
        '"\x00abc"',
        "contratti causa",
        "di",
        '"causa illecita" x',
        '"a b"',
        '"causa ""illecita"""',
        '"***"',
        "",
        "  ",
        "aiuoe",
        "PERCHÉ",
    ]
    + symbol_queries(),
)
def test_build_match_query_executes_safely_on_real_fts5(raw: str) -> None:
    with closing(sqlite3.connect(database=":memory:")) as connection:
        connection.execute("CREATE VIRTUAL TABLE passages USING fts5(text)")
        connection.execute("INSERT INTO passages VALUES (?)", ("contratto",))
        assert connection.execute(
            "SELECT text FROM passages WHERE passages MATCH ?",
            (build_match_query(raw="contratti"),),
        ).fetchall() == [("contratto",)]
        match = build_match_query(raw=raw)
        if match is not None:
            connection.execute(
                "SELECT text FROM passages WHERE passages MATCH ?", (match,)
            ).fetchall()


@pytest.mark.parametrize(
    ("highlighted", "expected"),
    [
        ("", []),
        ("<b>plain</b>", [SnippetPart(text="<b>plain</b>", match=False)]),
        (
            f"la {MATCH_START}causa{MATCH_END} è {MATCH_START}illecita{MATCH_END}",
            [
                SnippetPart(text="la ", match=False),
                SnippetPart(text="causa", match=True),
                SnippetPart(text=" è ", match=False),
                SnippetPart(text="illecita", match=True),
            ],
        ),
        (f"{MATCH_START}causa{MATCH_END}", [SnippetPart(text="causa", match=True)]),
    ],
)
def test_snippet_parts_preserves_text_and_marks_matches(
    highlighted: str, expected: list[SnippetPart]
) -> None:
    assert snippet_parts(highlighted=highlighted) == expected

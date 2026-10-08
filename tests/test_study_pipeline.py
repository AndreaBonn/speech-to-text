import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError
from study_fixtures import FakeChat, response_fixture, transcript_fixture

from sbobina.correction import CorrectorUnavailableError, InvalidResponseError
from sbobina.models import Transcript
from sbobina.settings import Settings
from sbobina.study_blocks import build_study_blocks
from sbobina.study_models import (
    Citation,
    DiscardCount,
    FailedBlock,
    QuestionItem,
    RejectionReason,
    StudyChapter,
    SummaryItem,
)
from sbobina.study_pipeline import StudyOptions, generate_study
from sbobina.study_validation import validate_chapter


def test_generate_study_keeps_supported_items_and_counts_rejections() -> None:
    payload = json.loads(response_fixture())
    chapter = payload["capitoli"][0]
    chapter["riassunto"].append(
        {
            "testo": "inventata",
            "citazioni": [{"passaggio": "S1", "testo": "il sole è verde"}],
        }
    )
    chapter["domande"].append({"domanda": "senza fonte", "citazioni": []})
    chat = FakeChat(responses=[json.dumps(payload)])
    progress: list[tuple[int, int]] = []
    result = generate_study(
        transcript=transcript_fixture(),
        chat=chat,
        options=StudyOptions(model="test"),
        on_progress=lambda done, total: progress.append((done, total)),
    )
    assert len(result.chapters[0].summary) == 1
    assert len(result.chapters[0].concepts) == 1
    assert len(result.chapters[0].questions) == 1
    assert result.discarded == (
        DiscardCount(reason=RejectionReason.QUOTE_NOT_FOUND, count=2),
    )
    assert result.failed_blocks == ()
    assert progress == [(1, 1)]
    assert chat.requests[0].num_predict == 2048
    assert "[S1] 00:10 la causa" in chat.requests[0].user_message


@pytest.mark.parametrize(
    "invalid", ["{", '{"capitoli": [{}]}', InvalidResponseError("bad")]
)
def test_generate_study_retries_invalid_json_then_records_failed_times(
    invalid: str | Exception,
) -> None:
    chat = FakeChat(responses=[invalid])
    progress: list[tuple[int, int]] = []
    result = generate_study(
        transcript=transcript_fixture(),
        chat=chat,
        options=StudyOptions(model="test"),
        on_progress=lambda done, total: progress.append((done, total)),
    )
    assert result.chapters == ()
    assert result.failed_blocks == (FailedBlock(start=0.0, end=15.5),)
    assert len(chat.requests) == 2
    assert progress == [(1, 1)]


def test_generate_study_invalid_json_retry_recovers_chapter() -> None:
    chat = FakeChat(responses=["{", "```json\n" + response_fixture() + "\n```"])
    result = generate_study(
        transcript=transcript_fixture(), chat=chat, options=StudyOptions(model="test")
    )
    assert result.chapters[0].title == "Contratto"
    assert len(chat.requests) == 2


def test_generate_study_unavailable_chat_propagates_error() -> None:
    with pytest.raises(CorrectorUnavailableError, match="down"):
        generate_study(
            transcript=transcript_fixture(),
            chat=FakeChat(responses=[CorrectorUnavailableError("down")]),
            options=StudyOptions(model="test"),
        )


def test_build_study_blocks_three_word_budget_preserves_passage_indices() -> None:
    transcript = transcript_fixture()
    blocks = build_study_blocks(transcript=transcript, max_words=3)
    assert [len(block.text.split()) - 2 * len(block.allowed) for block in blocks] == [
        3,
        3,
        3,
    ]
    assert [block.allowed for block in blocks] == [
        frozenset({0}),
        frozenset({1}),
        frozenset({1}),
    ]


def test_generate_study_hidden_words_rejects_unsupported_items() -> None:
    transcript = transcript_fixture()
    chat = FakeChat(responses=[response_fixture(quote="contratto è illecita")])
    result = generate_study(
        transcript=transcript,
        chat=chat,
        options=StudyOptions(model="test", block_words=3),
    )
    assert sum(len(c.summary) for c in result.chapters) == 1
    assert sum(d.count for d in result.discarded) == 7


def test_build_study_blocks_selects_longest_pause_in_last_twenty_percent() -> None:
    original = transcript_fixture().segments[1].words[0]
    words = tuple(
        replace(
            original,
            text=f" w{i}",
            start=float(i + (10 if i >= 8 else 0)),
            end=float(i + (10 if i >= 8 else 0)) + 0.5,
        )
        for i in range(12)
    )
    transcript = replace(
        transcript_fixture(),
        segments=(replace(transcript_fixture().segments[0], words=words, end=22.0),),
    )
    blocks = build_study_blocks(transcript=transcript, max_words=10)
    assert blocks[0].text.endswith("w7")
    assert blocks[1].text.startswith("[S0] 00:18 w8")


def test_build_study_blocks_empty_transcript_returns_empty() -> None:
    transcript = transcript_fixture()
    assert len(build_study_blocks(transcript=transcript, max_words=10)) == 1

    assert (
        build_study_blocks(transcript=replace(transcript, segments=()), max_words=10)
        == ()
    )


def test_build_study_blocks_zero_budget_raises_value_error() -> None:
    transcript = transcript_fixture()
    assert len(build_study_blocks(transcript=transcript, max_words=10)) == 1

    with pytest.raises(ValueError, match="positive"):
        build_study_blocks(transcript=transcript, max_words=0)


@pytest.mark.parametrize(
    ("field", "expected"), [("study_block_words", 1200), ("study_num_predict", 2048)]
)
def test_settings_study_limits_default_matches_contract(
    field: str, expected: int, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(name=f"SBOBINA_{field.upper()}", raising=False)

    monkeypatch.chdir(path=tmp_path)
    config = Settings()

    assert getattr(config, field) == expected


@pytest.mark.parametrize("field", ["study_block_words", "study_num_predict"])
def test_settings_study_limits_zero_rejected(field: str) -> None:
    assert getattr(Settings.model_validate({field: 1}), field) == 1

    with pytest.raises(ValidationError):
        Settings.model_validate({field: 0})


@pytest.fixture
def repeated_transcript() -> Transcript:
    template = transcript_fixture()
    words = tuple(
        replace(template.words[0], text=" " + token, start=float(i), end=i + 0.5)
        for i, token in enumerate(["alfa", "beta", "gamma", "alfa", "beta", "gamma"])
    )
    return replace(
        template, segments=(replace(template.segments[0], words=words, end=5.5),)
    )


@pytest.fixture
def repeated_chapter() -> StudyChapter:
    citation = Citation(segment_index=0, quote="alfa beta gamma")
    return StudyChapter(
        title="Contratto",
        start=0.0,
        summary=(SummaryItem(text="La causa è illecita.", citations=(citation,)),),
        concepts=(),
        questions=(QuestionItem(question="Com'è la causa?", citations=(citation,)),),
    )


def test_generate_study_first_repeat_keeps_grounded_chapter(
    repeated_transcript: Transcript, repeated_chapter: StudyChapter
) -> None:
    chat = FakeChat(
        responses=[
            response_fixture(quote="alfa beta gamma", passage="S0"),
            '{"capitoli": []}',
        ]
    )

    result = generate_study(
        transcript=repeated_transcript,
        chat=chat,
        options=StudyOptions(model="test", block_words=3),
    )

    assert result.chapters == (repeated_chapter,)
    assert result.discarded == (
        DiscardCount(reason=RejectionReason.TERM_NOT_IN_QUOTE, count=1),
    )
    assert result.failed_blocks == ()


def test_generate_study_later_repeat_rejects_ambiguous_items(
    repeated_transcript: Transcript, repeated_chapter: StudyChapter
) -> None:
    response = response_fixture(quote="alfa beta gamma", passage="S0")
    options = StudyOptions(model="test", block_words=3)
    first = generate_study(
        transcript=repeated_transcript,
        chat=FakeChat(responses=[response, '{"capitoli": []}']),
        options=options,
    )
    assert first.chapters == (repeated_chapter,)

    result = generate_study(
        transcript=repeated_transcript,
        chat=FakeChat(responses=['{"capitoli": []}', response]),
        options=options,
    )

    assert result.chapters == ()
    assert result.discarded == (
        DiscardCount(reason=RejectionReason.AMBIGUOUS_QUOTE, count=2),
        DiscardCount(reason=RejectionReason.TERM_NOT_IN_QUOTE, count=1),
    )
    assert result.failed_blocks == ()


def test_build_study_blocks_counts_lexical_words_and_preserves_input() -> None:
    template = transcript_fixture()
    original = replace(
        template.segments[0],
        words=(replace(template.words[0], text=" uno due tre quattro cinque"),),
    )
    transcript = replace(template, segments=(original,))
    blocks = build_study_blocks(transcript=transcript, max_words=2)
    assert [block.segments[0].text for block in blocks] == [
        "uno due",
        "tre quattro",
        "cinque",
    ]
    assert transcript.segments[0].text == "uno due tre quattro cinque"


def test_generate_study_unsorted_chapters_orders_by_citation_time() -> None:
    payload = json.loads(response_fixture())
    later = payload["capitoli"][0]
    earlier = json.loads(response_fixture(quote="inizio della lezione", passage="S0"))[
        "capitoli"
    ][0]
    earlier["titolo"] = "Introduzione"
    earlier["inizio"] = 999
    payload["capitoli"] = [later, earlier]
    result = generate_study(
        transcript=transcript_fixture(),
        chat=FakeChat(responses=[json.dumps(payload)]),
        options=StudyOptions(model="test"),
    )
    assert [(c.title, c.start) for c in result.chapters] == [
        ("Introduzione", 0.0),
        ("Contratto", 10.0),
    ]


def test_generate_study_multiple_blocks_reports_each_completion() -> None:
    progress: list[tuple[int, int]] = []
    generate_study(
        transcript=transcript_fixture(),
        chat=FakeChat(responses=['{"capitoli": []}']),
        options=StudyOptions(model="test", block_words=3),
        on_progress=lambda done, total: progress.append((done, total)),
    )
    assert progress == [(1, 3), (2, 3), (3, 3)]


def test_generate_study_keeps_an_empty_revision_when_none_is_given() -> None:
    # The revision must come from the saved file bytes, as the web reader computes it;
    # re-serialising the transcript here would give a different hash for the same file.
    result = generate_study(
        transcript=transcript_fixture(),
        chat=FakeChat(responses=[response_fixture()]),
        options=StudyOptions(model="test"),
    )
    given = generate_study(
        transcript=transcript_fixture(),
        chat=FakeChat(responses=[response_fixture()]),
        options=StudyOptions(model="test", source_revision="abc"),
    )

    assert result.source_revision == ""
    assert given.source_revision == "abc"


@pytest.mark.parametrize(
    ("block_words", "num_predict"), [(0, 2048), (1200, 0), (-1, 2048)]
)
def test_study_options_rejects_non_positive_limits(
    block_words: int, num_predict: int
) -> None:
    with pytest.raises(ValueError, match="positive"):
        StudyOptions(model="test", block_words=block_words, num_predict=num_predict)


def test_validate_chapter_rejects_quote_missing_from_the_original_segments() -> None:
    transcript = transcript_fixture()
    chapter = generate_study(
        transcript=transcript,
        chat=FakeChat(responses=[response_fixture(quote="contratto è illecita")]),
        options=StudyOptions(model="test"),
    ).chapters[0]
    quoted = transcript.segments[1]
    changed = replace(
        quoted, words=(*quoted.words[:-1], replace(quoted.words[-1], text=" lecita"))
    )
    original = (transcript.segments[0], changed)
    allowed = frozenset({0, 1})

    kept, _ = validate_chapter(
        chapter=chapter, segments=transcript.segments, allowed=allowed
    )
    dropped, counts = validate_chapter(
        chapter=chapter,
        segments=transcript.segments,
        allowed=allowed,
        original=original,
    )

    items = len(chapter.summary) + len(chapter.concepts) + len(chapter.questions)
    assert kept == chapter
    assert (dropped, dict(counts)) == (None, {RejectionReason.QUOTE_NOT_FOUND: items})


def _cut_study_reply() -> str:
    """One full chapter, then a second cut by the token limit (measured: 3 of 5 blocks)."""
    whole = json.loads(response_fixture())
    whole["capitoli"].append(dict(whole["capitoli"][0], titolo="Seconda"))
    text = json.dumps(whole)
    return text[: text.rindex('"concetti"')]


def test_generate_study_keeps_the_complete_chapters_of_a_cut_reply() -> None:
    chat = FakeChat(responses=[_cut_study_reply()])

    result = generate_study(
        transcript=transcript_fixture(), chat=chat, options=StudyOptions(model="test")
    )

    assert [chapter.title for chapter in result.chapters] == ["Contratto"]
    assert result.failed_blocks == ()


def test_generate_study_still_fails_a_block_with_no_complete_chapter() -> None:
    cut = response_fixture()[:40]
    result = generate_study(
        transcript=transcript_fixture(),
        chat=FakeChat(responses=[cut]),
        options=StudyOptions(model="test"),
    )

    assert result.chapters == ()
    assert len(result.failed_blocks) == 1

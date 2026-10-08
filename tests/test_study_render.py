from dataclasses import replace
from pathlib import Path

import pytest
from study_fixtures import FakeChat, response_fixture, transcript_fixture

from sbobina.render import RenderOptions
from sbobina.study_models import Citation, FailedBlock, SummaryItem
from sbobina.study_pipeline import StudyOptions, generate_study
from sbobina.study_render import (
    _render_item,
    load_study,
    render_study_markdown,
    save_study,
)

OPTIONS = RenderOptions(
    uncertain_threshold=0.7, paragraph_gap_s=2.0, paragraph_max_s=120.0
)


def test_render_item_invalid_citation_returns_no_lines() -> None:
    transcript = transcript_fixture()
    valid = SummaryItem(
        text="Valid summary",
        citations=(
            Citation(segment_index=1, quote="la causa del contratto è illecita"),
        ),
    )
    invalid = SummaryItem(
        text="Invalid summary",
        citations=(
            Citation(segment_index=1, quote="words absent from this transcript"),
        ),
    )

    rejected = _render_item(item=invalid, transcript=transcript, paragraphs={1: 2})
    rendered = _render_item(item=valid, transcript=transcript, paragraphs={1: 2})

    assert rejected == []
    assert rendered == [
        "- Valid summary",
        "  > §2 00:10: la causa del contratto è illecita",
    ]


def test_render_study_markdown_recomputes_paragraph_but_preserves_timestamp() -> None:
    transcript = transcript_fixture()
    result = generate_study(
        transcript=transcript,
        chat=FakeChat(responses=[response_fixture()]),
        options=StudyOptions(model="test"),
    )
    separate = render_study_markdown(
        result=result, transcript=transcript, options=OPTIONS
    )
    joined = render_study_markdown(
        result=result,
        transcript=transcript,
        options=replace(OPTIONS, paragraph_gap_s=10.0),
    )
    assert "§2 00:10" in separate
    assert "§1 00:10" in joined
    assert "la causa del contratto è illecita" in joined
    assert "- Com'è la causa?" in joined
    assert "## Contratto (00:10)" in joined


def test_load_study_drops_changed_quote_without_persisting_word_indices(
    tmp_path: Path,
) -> None:
    transcript = transcript_fixture()
    result = generate_study(
        transcript=transcript,
        chat=FakeChat(responses=[response_fixture()]),
        options=StudyOptions(model="test"),
    )
    result = replace(
        result, chapters=(replace(result.chapters[0], concepts=(), questions=()),)
    )
    path = tmp_path / "audio.studio.json"
    save_study(result=result, json_path=path, transcript=transcript, options=OPTIONS)
    loaded = load_study(path=path, transcript=transcript)
    assert loaded.result == result
    assert loaded.stale_dropped == 0
    content = path.read_text()
    assert '"segment_index": 1' in content
    assert "word_index" not in content
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "audio.studio.json",
        "audio.studio.md",
    ]


def test_load_study_changed_word_drops_one_item(tmp_path: Path) -> None:
    transcript = transcript_fixture()
    result = generate_study(
        transcript=transcript,
        chat=FakeChat(responses=[response_fixture()]),
        options=StudyOptions(model="test"),
    )
    result = replace(
        result, chapters=(replace(result.chapters[0], concepts=(), questions=()),)
    )
    path = tmp_path / "audio.studio.json"
    save_study(result=result, json_path=path, transcript=transcript, options=OPTIONS)
    segment = transcript.segments[1]
    changed = replace(
        segment,
        words=(
            segment.words[0],
            replace(segment.words[1], text=" ragione"),
            *segment.words[2:],
        ),
    )
    current = replace(transcript, segments=(transcript.segments[0], changed))
    stale = load_study(path=path, transcript=current)
    assert stale.result.chapters == ()
    assert stale.stale_dropped == 1
    assert "La causa è illecita" not in render_study_markdown(
        result=result, transcript=current, options=OPTIONS
    )


def test_save_study_replaces_files_without_truncating_open_readers(
    tmp_path: Path,
) -> None:
    transcript = transcript_fixture()
    result = generate_study(
        transcript=transcript,
        chat=FakeChat(responses=[response_fixture()]),
        options=StudyOptions(model="test"),
    )
    path = tmp_path / "audio.studio.json"
    path.write_text("previous json")
    path.with_suffix(".md").write_text("previous markdown")
    with path.open() as old_json, path.with_suffix(".md").open() as old_md:
        save_study(
            result=result, json_path=path, transcript=transcript, options=OPTIONS
        )
        assert old_json.read() == "previous json"
        assert old_md.read() == "previous markdown"
    assert load_study(path=path, transcript=transcript).result == result
    assert "§2 00:10" in path.with_suffix(".md").read_text()


def test_save_study_bad_destination_keeps_previous_json(tmp_path: Path) -> None:
    transcript = transcript_fixture()
    result = generate_study(
        transcript=transcript,
        chat=FakeChat(responses=['{"capitoli": []}']),
        options=StudyOptions(model="test"),
    )
    path = tmp_path / "audio.studio.json"
    path.write_text("previous json")
    path.with_suffix(".md").mkdir()
    with pytest.raises(OSError):
        save_study(
            result=result, json_path=path, transcript=transcript, options=OPTIONS
        )
    assert path.read_text() == "previous json"
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "audio.studio.json",
        "audio.studio.md",
    ]


def test_render_study_markdown_lists_failed_blocks_with_their_times() -> None:
    transcript = transcript_fixture()
    result = generate_study(
        transcript=transcript,
        chat=FakeChat(responses=[response_fixture()]),
        options=StudyOptions(model="test"),
    )
    failed = replace(result, failed_blocks=(FailedBlock(start=65.0, end=130.0),))

    markdown = render_study_markdown(
        result=failed, transcript=transcript, options=OPTIONS
    )
    plain = render_study_markdown(result=result, transcript=transcript, options=OPTIONS)

    assert "## Blocchi non elaborati" not in plain
    assert "## Blocchi non elaborati\n\n- 01:05 – 02:10" in markdown

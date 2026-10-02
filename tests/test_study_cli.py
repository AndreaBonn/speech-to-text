from dataclasses import replace
from pathlib import Path

import pytest
from study_fixtures import FakeChat, response_fixture, transcript_fixture

from sbobina.cli import build_parser, main
from sbobina.correction import CorrectorUnavailableError
from sbobina.models import save_transcript
from sbobina.study_command import cmd_studio
from sbobina.study_pipeline import source_revision
from sbobina.study_render import load_study


def test_cmd_studio_writes_atomic_pair_using_corrected_source(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO", logger="sbobina")
    transcript = transcript_fixture()
    path = tmp_path / "audio.json"
    save_transcript(transcript=replace(transcript, segments=()), path=path)
    corrected = path.with_suffix(".corretto.json")
    save_transcript(transcript=transcript, path=corrected)
    args = build_parser().parse_args(["studio", str(path), "--model", "custom"])
    chat = FakeChat(responses=[response_fixture()])
    assert cmd_studio(args=args, chat=chat) == 0
    loaded = load_study(path=path.with_suffix(".studio.json"), transcript=transcript)
    assert loaded.result.source_variant == "corrected"
    assert loaded.result.source_revision == source_revision(
        content=corrected.read_text()
    )
    assert loaded.result.model == "custom"
    assert "§2 00:10" in path.with_suffix(".studio.md").read_text()
    assert chat.requests[0].model == "custom"
    assert "Elaborati 1 blocchi di studio su 1" in caplog.text


def test_cmd_studio_unavailable_keeps_both_previous_files(tmp_path: Path) -> None:
    path = tmp_path / "audio.json"
    save_transcript(transcript=transcript_fixture(), path=path)
    json_path = path.with_suffix(".studio.json")
    md_path = path.with_suffix(".studio.md")
    json_path.write_text("previous json")
    md_path.write_text("previous markdown")
    args = build_parser().parse_args(["studio", str(path)])
    assert (
        cmd_studio(
            args=args, chat=FakeChat(responses=[CorrectorUnavailableError("down")])
        )
        == 1
    )
    assert json_path.read_text() == "previous json"
    assert md_path.read_text() == "previous markdown"
    assert main(argv=["studio", str(tmp_path / "missing.json")]) == 1


def test_cmd_studio_corrected_input_has_no_double_suffix(tmp_path: Path) -> None:
    path = tmp_path / "audio.corretto.json"
    save_transcript(transcript=transcript_fixture(), path=path)
    args = build_parser().parse_args(["studio", str(path)])
    assert cmd_studio(args=args, chat=FakeChat(responses=[response_fixture()])) == 0
    assert (tmp_path / "audio.studio.md").is_file()
    assert not (tmp_path / "audio.corretto.studio.md").exists()

from pathlib import Path

import pytest
from conftest import make_segment, make_transcript, make_word

from sbobina.cli import main
from sbobina.models import save_transcript


@pytest.fixture
def transcript_json(tmp_path: Path) -> Path:
    transcript = make_transcript(
        [make_segment([make_word(" teorema", 0.0), make_word(" Sennberg", 0.5, 0.5)])]
    )
    path = tmp_path / "lezione.json"
    save_transcript(transcript, path)
    return path


def test_rendi_writes_markdown_next_to_json(transcript_json: Path) -> None:
    exit_code = main(["rendi", str(transcript_json)])

    markdown = transcript_json.with_suffix(".md").read_text(encoding="utf-8")
    assert exit_code == 0
    assert "teorema [?Sennberg?]" in markdown


def test_rendi_threshold_override_changes_flagging(transcript_json: Path) -> None:
    main(["rendi", str(transcript_json), "--soglia", "0.4"])

    markdown = transcript_json.with_suffix(".md").read_text(encoding="utf-8")
    assert "[?" not in markdown
    assert "teorema Sennberg" in markdown


def test_wer_reads_json_hypothesis(
    transcript_json: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reference = tmp_path / "gold.txt"
    reference.write_text("Teorema di Heisenberg.", encoding="utf-8")

    exit_code = main(["wer", str(reference), str(transcript_json)])

    assert exit_code == 0
    assert (
        "WER 66.67% su 3 parole: 1 sostituite, 1 mancanti, 0 in più"
        in capsys.readouterr().out
    )


def test_missing_input_file_returns_error_code(tmp_path: Path) -> None:
    assert main(["rendi", str(tmp_path / "non-esiste.json")]) == 1


@pytest.mark.parametrize("threshold", ["0", "1.5", "abc"])
def test_rendi_rejects_threshold_outside_zero_one(transcript_json: Path, threshold: str) -> None:
    with pytest.raises(SystemExit):
        main(["rendi", str(transcript_json), "--soglia", threshold])


def test_trascrivi_output_dir_that_is_a_file_returns_error_code(tmp_path: Path) -> None:
    audio = tmp_path / "lezione.m4a"
    audio.write_bytes(b"")
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("x", encoding="utf-8")

    assert main(["trascrivi", str(audio), "-o", str(not_a_dir)]) == 1

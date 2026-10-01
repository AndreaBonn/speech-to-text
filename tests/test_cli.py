from pathlib import Path

import pytest
from conftest import make_segment, make_transcript, make_word

from sbobina import llm_corrector
from sbobina.cli import main
from sbobina.correction import Corrector, CorrectorUnavailableError, Edit
from sbobina.models import load_transcript, save_transcript
from sbobina.settings import Settings


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
def test_rendi_rejects_threshold_outside_zero_one(
    transcript_json: Path, threshold: str
) -> None:
    with pytest.raises(SystemExit):
        main(["rendi", str(transcript_json), "--soglia", threshold])


def test_trascrivi_output_dir_that_is_a_file_returns_error_code(tmp_path: Path) -> None:
    audio = tmp_path / "lezione.m4a"
    audio.write_bytes(b"")
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("x", encoding="utf-8")

    assert main(["trascrivi", str(audio), "-o", str(not_a_dir)]) == 1


def test_correggi_writes_corrected_transcript_and_report(
    transcript_json: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_factory(model: str, host: str, subject: str | None) -> Corrector:
        assert subject == "fisica"
        return lambda text, context: [Edit(original="Sennberg", corrected="Heisenberg")]

    monkeypatch.setattr(llm_corrector, "make_ollama_corrector", fake_factory)

    exit_code = main(["correggi", str(transcript_json), "--materia", "fisica"])

    corrected_md = transcript_json.with_name("lezione.corretto.md").read_text(
        encoding="utf-8"
    )
    report = transcript_json.with_name("lezione.correzioni.md").read_text(
        encoding="utf-8"
    )
    assert exit_code == 0
    assert "teorema Heisenberg" in corrected_md
    assert "[?" not in corrected_md
    assert "Sennberg → **Heisenberg**" in report
    assert load_transcript(transcript_json.with_name("lezione.corretto.json")).text == (
        "teorema Heisenberg"
    )


def test_correggi_model_option_reaches_corrector_and_report(
    transcript_json: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models: list[str] = []

    def fake_factory(model: str, host: str, subject: str | None) -> Corrector:
        models.append(model)
        return lambda text, context: []

    monkeypatch.setattr(llm_corrector, "make_ollama_corrector", fake_factory)

    exit_code = main(["correggi", str(transcript_json), "--modello", "gemma3:4b"])

    report = transcript_json.with_name("lezione.correzioni.md").read_text(
        encoding="utf-8"
    )
    assert exit_code == 0
    assert models == ["gemma3:4b"]
    assert "gemma3:4b" in report


def test_correggi_returns_error_when_ollama_unreachable(
    transcript_json: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_corrector(text: str, context: str) -> list[Edit]:
        raise CorrectorUnavailableError("Failed to connect to Ollama")

    monkeypatch.setattr(
        llm_corrector,
        "make_ollama_corrector",
        lambda model, host, subject: failing_corrector,
    )

    assert main(["correggi", str(transcript_json)]) == 1
    assert not transcript_json.with_name("lezione.corretto.json").exists()


def test_correggi_interrupted_midway_saves_done_work_and_returns_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transcript = make_transcript(
        [make_segment([make_word(f" w{i}", i * 30.0, 0.5)]) for i in range(300)]
    )
    path = tmp_path / "lezione.json"
    save_transcript(transcript, path)
    calls = 0

    def flaky_corrector(text: str, context: str) -> list[Edit]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise CorrectorUnavailableError("ollama crashed")
        return [Edit(original="w1", corrected="w11")]

    monkeypatch.setattr(
        llm_corrector,
        "make_ollama_corrector",
        lambda model, host, subject: flaky_corrector,
    )

    assert main(["correggi", str(path)]) == 1
    report = path.with_name("lezione.correzioni.md").read_text(encoding="utf-8")
    assert "Correzione interrotta a [01:40:00]" in report
    assert len(load_transcript(path.with_name("lezione.corretto.json")).words) == 300


@pytest.mark.parametrize(
    ("argv", "port", "browser"),
    [(["web"], 8765, True), (["web", "--port", "9000", "--no-browser"], 9000, False)],
)
def test_web_port_option_reaches_server_config(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], port: int, browser: bool
) -> None:
    from sbobina.web import launcher

    calls: list[tuple[int, bool]] = []

    def fake_run_server(config: Settings, open_browser: bool) -> int:
        calls.append((config.web_port, open_browser))
        return 0

    monkeypatch.setattr(launcher, "run_server", fake_run_server)
    monkeypatch.setenv("SBOBINA_WEB_PORT", "8765")

    assert main(argv) == 0
    assert calls == [(port, browser)]


@pytest.mark.parametrize("port", ["0", "70000", "abc"])
def test_web_invalid_port_is_rejected(port: str) -> None:
    with pytest.raises(SystemExit):
        main(["web", "--port", port])

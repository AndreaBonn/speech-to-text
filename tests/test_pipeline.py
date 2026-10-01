from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import make_segment, make_transcript, make_word

from sbobina import pipeline
from sbobina.correction import (
    CorrectionResult,
    CorrectorUnavailableError,
    Edit,
    InvalidResponseError,
)
from sbobina.models import load_transcript, save_transcript
from sbobina.settings import Settings


def test_with_progress_notifies_after_every_call() -> None:
    calls: list[tuple[int, int]] = []
    edits = [Edit(original="Sennberg", corrected="Heisenberg")]
    tracked = pipeline.with_progress(
        lambda text, context: edits,
        total=3,
        on_done=lambda done, count: calls.append((done, count)),
    )

    results = [tracked("Sennberg", "") for _ in range(3)]

    assert calls == [(1, 3), (2, 3), (3, 3)]
    assert results == [edits] * 3


def test_with_progress_counts_failed_calls_and_reraises() -> None:
    # A chunk with an invalid answer is kept as is by correct_transcript, so it
    # is done all the same: skipping it would leave the bar short of total.
    calls: list[tuple[int, int]] = []

    def failing(text: str, context: str) -> list[Edit]:
        raise InvalidResponseError("not json")

    tracked = pipeline.with_progress(
        failing, total=1, on_done=lambda done, count: calls.append((done, count))
    )

    with pytest.raises(InvalidResponseError):
        tracked("x", "")
    assert calls == [(1, 1)]


def test_label_transcript_names_json_and_markdown_after_the_upload(
    tmp_path: Path,
) -> None:
    json_path = tmp_path / "audio.json"
    transcript = make_transcript([make_segment([make_word(" ciao", 0.0, 0.5)])])
    save_transcript(replace(transcript, source=str(tmp_path / "audio.m4a")), json_path)

    pipeline.label_transcript(
        json_path=json_path, source_name="Lezione 3.m4a", config=Settings()
    )

    assert load_transcript(json_path).source == "Lezione 3.m4a"
    heading = json_path.with_suffix(".md").read_text(encoding="utf-8").splitlines()[0]
    assert heading == "# Sbobinatura: Lezione 3.m4a"


def test_transcribe_to_dir_writes_outputs_and_forwards_callback(tmp_path: Path) -> None:
    transcript = make_transcript([make_segment([make_word(" ciao", 0.0, 0.5)])])
    audio = tmp_path / "lezione.m4a"
    output = tmp_path / "nested" / "output"
    calls: list[tuple[float, float]] = []
    config = Settings(uncertain_threshold=0.4)

    def on_progress(end: float, duration: float) -> None:
        calls.append((end, duration))

    with patch("sbobina.transcriber.transcribe_file", return_value=transcript) as run:
        path = pipeline.transcribe_to_dir(
            audio,
            output_dir=output,
            config=config,
            on_progress=on_progress,
        )

    run.assert_called_once_with(audio, config=config, on_progress=on_progress)
    assert path == output / "lezione.json"
    assert load_transcript(path) == transcript
    markdown = path.with_suffix(".md").read_text(encoding="utf-8")
    assert "ciao" in markdown
    assert "[?" not in markdown


@pytest.fixture
def transcript_json(tmp_path: Path) -> Path:
    transcript = make_transcript(
        [
            make_segment(
                [make_word(" teorema", 0.0), make_word(" Sennberg", 0.5, 0.5)]
            ),
            make_segment([make_word(" Grazie.", 20.0)]),
        ]
    )
    path = tmp_path / "lezione.json"
    save_transcript(transcript, path)
    return path


def test_correct_to_dir_success_writes_cleaned_outputs_and_progress(
    transcript_json: Path,
) -> None:
    calls: list[tuple[int, int]] = []
    with (
        patch("sbobina.llm_corrector.ensure_model") as ensure,
        patch("sbobina.llm_corrector.make_ollama_corrector") as factory,
    ):
        factory.return_value = lambda text, context: [
            Edit(original="Sennberg", corrected="Heisenberg")
        ]
        outcome = pipeline.correct_to_dir(
            transcript_json,
            config=Settings(ollama_model="test-model", ollama_host="http://gpu:1"),
            subject="fisica",
            on_progress=lambda done, total: calls.append((done, total)),
        )

    ensure.assert_called_once_with(model="test-model", host="http://gpu:1")
    factory.assert_called_once_with(
        model="test-model", host="http://gpu:1", subject="fisica"
    )
    assert outcome.interrupted is False
    assert outcome.result.interrupted_at is None
    assert calls == [(1, 1)]
    assert outcome.corrected_json == transcript_json.with_name("lezione.corretto.json")
    assert load_transcript(outcome.corrected_json).text == "teorema Heisenberg"
    markdown = outcome.corrected_json.with_suffix(".md").read_text(encoding="utf-8")
    report_path = transcript_json.with_name("lezione.correzioni.md")
    report = report_path.read_text(encoding="utf-8")
    assert "teorema Heisenberg" in markdown
    assert "Sennberg → **Heisenberg**" in report
    assert all(text in report for text in ("Grazie.", "test-model"))


def test_correct_to_dir_midway_failure_writes_partial_outputs(tmp_path: Path) -> None:
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
            raise CorrectorUnavailableError("Ollama crashed")
        return [Edit(original="w1", corrected="w11")]

    with (
        patch("sbobina.llm_corrector.ensure_model"),
        patch(
            "sbobina.llm_corrector.make_ollama_corrector", return_value=flaky_corrector
        ),
    ):
        outcome = pipeline.correct_to_dir(path, config=Settings(), subject=None)

    assert outcome.interrupted and outcome.result.interrupted_at == 6000.0
    assert outcome.corrected_json == path.with_name("lezione.corretto.json")
    corrected = load_transcript(outcome.corrected_json)
    assert len(corrected.words) == 300
    assert corrected.words[1].text.strip() == "w11"
    assert corrected.words[200] == transcript.words[200]
    markdown_path = outcome.corrected_json.with_suffix(".md")
    assert "w11" in markdown_path.read_text(encoding="utf-8")
    report = path.with_name("lezione.correzioni.md").read_text(encoding="utf-8")
    assert "Correzione interrotta a [01:40:00]" in report


def test_correct_to_dir_first_chunk_failure_preserves_only_input(
    transcript_json: Path,
) -> None:
    def failing_corrector(text: str, context: str) -> list[Edit]:
        raise CorrectorUnavailableError("Failed to connect to Ollama")

    with (
        patch("sbobina.llm_corrector.ensure_model"),
        patch(
            "sbobina.llm_corrector.make_ollama_corrector",
            return_value=failing_corrector,
        ),
    ):
        outcome = pipeline.correct_to_dir(
            transcript_json, config=Settings(), subject=None
        )

    assert outcome.interrupted is True
    assert outcome.result.interrupted_at == 0.0
    assert outcome.corrected_json is None
    assert list(transcript_json.parent.iterdir()) == [transcript_json]
    assert load_transcript(transcript_json).text == "teorema Sennberg Grazie."


@pytest.mark.parametrize(("interrupted_at", "expected"), [(None, False), (0.0, True)])
def test_correction_outcome_interrupted_follows_result(
    interrupted_at: float | None, expected: bool
) -> None:
    transcript = make_transcript([make_segment([make_word(" ciao", 0.0)])])
    result = CorrectionResult(
        transcript=transcript, applied=[], rejected=[], interrupted_at=interrupted_at
    )

    outcome = pipeline.CorrectionOutcome(result=result, corrected_json=None)

    assert outcome.interrupted is expected


def test_corrected_paths_derive_from_transcript_stem() -> None:
    corrected_json, report = pipeline.corrected_paths(Path("out/lezione.json"))

    assert corrected_json == Path("out/lezione.corretto.json")
    assert report == Path("out/lezione.correzioni.md")


def test_with_progress_does_not_count_a_call_that_stops_the_run() -> None:
    # Ollama gone: correct_transcript stops and leaves this chunk uncorrected.
    calls: list[tuple[int, int]] = []

    def unavailable(text: str, context: str) -> list[Edit]:
        raise CorrectorUnavailableError("down")

    tracked = pipeline.with_progress(
        unavailable, total=1, on_done=lambda done, count: calls.append((done, count))
    )

    with pytest.raises(CorrectorUnavailableError):
        tracked("x", "")
    assert calls == []

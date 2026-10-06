from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from sbobina import llm_corrector, llm_factory
from sbobina.cleanup import remove_silence_fillers
from sbobina.correction import (
    CorrectionResult,
    Corrector,
    Edit,
    InvalidResponseError,
    chunk_segments,
    correct_transcript,
)
from sbobina.llm_chain import ServedByRecorder
from sbobina.models import Segment, Transcript, load_transcript, save_transcript
from sbobina.render import RenderOptions, render_markdown
from sbobina.report import render_corrections_report
from sbobina.settings import Settings
from sbobina.transcriber import ProgressCallback


@dataclass(frozen=True)
class CorrectionOutcome:
    result: CorrectionResult
    corrected_json: Path | None  # None when nothing was corrected before a stop

    @property
    def interrupted(self) -> bool:
        return self.result.interrupted_at is not None


def with_progress(
    corrector: Corrector, total: int, on_done: Callable[[int, int], None]
) -> Corrector:
    """Wrap a corrector with notifications after successful calls.

    Parameters
    ----------
    corrector : Corrector
        Correction callable; its exceptions propagate. An invalid answer still
        counts, since ``correct_transcript`` keeps that chunk and moves on; an
        unavailable model does not, since the run stops there.
    total : int
        Number of expected calls.
    on_done : Callable[[int, int], None]
        Receives completed/total counts after every call; throttling is up to
        the caller.
    """
    done = 0

    def advance() -> None:
        nonlocal done
        done += 1
        on_done(done, total)

    def tracked(text: str, context: str) -> list[Edit]:
        try:
            edits = corrector(text, context)
        except InvalidResponseError:
            advance()
            raise
        advance()
        return edits

    return tracked


def corrected_paths(json_path: Path) -> tuple[Path, Path]:
    """Return the corrected transcript and corrections report paths."""
    stem = json_path.with_suffix("")
    return (
        stem.with_name(f"{stem.name}.corretto.json"),
        stem.with_name(f"{stem.name}.correzioni.md"),
    )


def write_markdown(transcript: Transcript, json_path: Path, config: Settings) -> Path:
    """Render ``transcript`` next to ``json_path`` and return the ``.md`` path."""
    options = RenderOptions(
        uncertain_threshold=config.uncertain_threshold,
        paragraph_gap_s=config.paragraph_gap_s,
        paragraph_max_s=config.paragraph_max_s,
    )
    markdown_path = json_path.with_suffix(".md")
    markdown_path.write_text(render_markdown(transcript, options), encoding="utf-8")
    return markdown_path


def label_transcript(json_path: Path, source_name: str, config: Settings) -> None:
    """Show ``source_name`` instead of the on-disk audio name in JSON and markdown."""
    transcript = replace(load_transcript(json_path), source=source_name)
    save_transcript(transcript, json_path)
    write_markdown(transcript, json_path=json_path, config=config)


def transcribe_to_dir(
    audio_path: Path,
    output_dir: Path,
    config: Settings,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """Transcribe audio, write JSON/Markdown into ``output_dir``; return the JSON path.

    Parameters
    ----------
    audio_path, output_dir : Path
        Source audio and destination directory, created if missing.
    config : Settings
        Whisper and rendering configuration for this run.
    on_progress : ProgressCallback | None
        Receives processed audio seconds and total duration per segment.
    """
    from sbobina.transcriber import transcribe_file

    output_dir.mkdir(parents=True, exist_ok=True)
    transcript = transcribe_file(audio_path, config=config, on_progress=on_progress)
    json_path = output_dir / f"{audio_path.stem}.json"
    save_transcript(transcript, json_path)
    write_markdown(transcript, json_path=json_path, config=config)
    return json_path


def _correct(
    transcript: Transcript,
    config: Settings,
    subject: str | None,
    on_progress: Callable[[int, int], None] | None,
) -> tuple[CorrectionResult, dict[str, int]]:
    recorder = ServedByRecorder()
    chat = llm_factory.build_from_settings(settings=config, recorder=recorder)
    corrector = llm_corrector.make_ollama_corrector(
        chat=chat, model=config.ollama_model, subject=subject
    )
    chunk_words = config.correction_chunk_words
    total = len(chunk_segments(transcript.segments, max_words=chunk_words))
    if on_progress is not None:
        corrector = with_progress(corrector, total=total, on_done=on_progress)
    result = correct_transcript(transcript, corrector=corrector, max_words=chunk_words)
    return result, recorder.snapshot()


@dataclass(frozen=True, kw_only=True)
class _CorrectionWrite:
    json_path: Path
    result: CorrectionResult
    removed: list[Segment]
    served_by: dict[str, int]


def _write_correction_outputs(write: _CorrectionWrite, config: Settings) -> Path:
    corrected_json, report_path = corrected_paths(write.json_path)
    save_transcript(write.result.transcript, corrected_json)
    write_markdown(write.result.transcript, json_path=corrected_json, config=config)
    report = render_corrections_report(
        write.result,
        model=config.ollama_model,
        removed=write.removed,
        served_by=write.served_by,
    )
    report_path.write_text(report, encoding="utf-8")
    return corrected_json


def correct_to_dir(
    json_path: Path,
    config: Settings,
    subject: str | None,
    on_progress: Callable[[int, int], None] | None = None,
) -> CorrectionOutcome:
    """Correct ``json_path`` with the configured Ollama model.

    Outputs are written unless the model stopped before the first chunk, so a
    run interrupted midway still keeps the part already corrected.

    Parameters
    ----------
    json_path : Path
        Transcript produced by ``transcribe_to_dir``.
    config : Settings
        Ollama model/host, chunk size and rendering configuration.
    subject : str | None
        Subject of the lecture, given to the model as context.
    on_progress : Callable[[int, int], None] | None
        Receives corrected/total chunk counts every ten chunks and at the end.
    """
    transcript, removed = remove_silence_fillers(load_transcript(json_path))
    result, served_by = _correct(
        transcript, config=config, subject=subject, on_progress=on_progress
    )
    stopped_at = result.interrupted_at
    if stopped_at is not None and stopped_at <= transcript.segments[0].start:
        return CorrectionOutcome(result=result, corrected_json=None)
    corrected_json = _write_correction_outputs(
        _CorrectionWrite(
            json_path=json_path, result=result, removed=removed, served_by=served_by
        ),
        config=config,
    )
    return CorrectionOutcome(result=result, corrected_json=corrected_json)

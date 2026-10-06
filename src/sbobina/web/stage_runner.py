import argparse
import logging
import os
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from threading import Thread

from sbobina.correction import CorrectorUnavailableError
from sbobina.llm_errors import ChainExhaustedError
from sbobina.log_redaction import install_redaction
from sbobina.notices import USER_NOTICE
from sbobina.pipeline import (
    CorrectionOutcome,
    correct_to_dir,
    label_transcript,
    transcribe_to_dir,
)
from sbobina.settings import Settings, settings
from sbobina.web.generation_runner import run_generation_stage
from sbobina.web.job_models import JobRecord, JobStage
from sbobina.web.job_store import JobStore
from sbobina.web.ocr_runner import run_ocr_stage
from sbobina.web.study_stage import generate_study_files
from sbobina.web.supervisor import OLLAMA_UNAVAILABLE_EXIT

logger = logging.getLogger("sbobina")
PROGRESS_INTERVAL_S = 1.0
NON_AUDIO_SUFFIXES = frozenset({".part", ".json", ".md", ".tmp"})
GENERATION_STAGE = "generation"
OCR_STAGE = "ocr"
STAGES = {
    "transcribe": JobStage.TRANSCRIBING,
    "correct": JobStage.CORRECTING,
    "study": JobStage.STUDY,
}
StagePipeline = Callable[..., Path | CorrectionOutcome]


@dataclass
class _Progress:
    store: JobStore
    job_id: str
    stage: JobStage
    now: Callable[[], float]
    started: float = field(init=False)
    last_write: float | None = field(default=None, init=False)
    audio_s: float = field(default=0.0, init=False)
    notice: str | None = field(default=None, init=False)
    fraction: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self.started = self.now()

    def __call__(self, done: float, total: float) -> None:
        timestamp = self.now()
        if self.stage == JobStage.TRANSCRIBING:
            self.audio_s = max(0.0, float(done))
        if (
            self.stage != JobStage.STUDY
            and self.last_write is not None
            and timestamp - self.last_write < PROGRESS_INTERVAL_S
        ):
            return
        fraction = min(1.0, max(0.0, done / total)) if total > 0 else 0.0
        self._write(fraction=fraction, timestamp=timestamp)

    def finish(self) -> None:
        self._write(fraction=1.0, timestamp=self.now())

    def finish_write(self) -> None:
        """Write now, keeping the last fraction: a notice must not wait 1 s."""
        self._write(fraction=self.fraction, timestamp=self.now())

    def _write(self, fraction: float, timestamp: float) -> None:
        self.fraction = fraction
        self.store.write_progress(
            job_id=self.job_id,
            progress={
                "stage": self.stage.value,
                "progress": float(fraction),
                "audio_s": self.audio_s,
                "elapsed_s": max(0.0, timestamp - self.started),
                "notice": self.notice,
            },
        )
        self.last_write = timestamp


class _NoticeHandler(logging.Handler):
    """Copies log records marked as user notices into the job's progress."""

    def __init__(self, progress: _Progress) -> None:
        super().__init__(level=logging.INFO)
        self.progress = progress

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, USER_NOTICE, False):
            self.progress.notice = record.getMessage()
            self.progress.finish_write()


def _find_audio(job_dir: Path) -> Path:
    candidates = [
        path
        for path in job_dir.glob("audio.*")
        if path.is_file() and path.suffix.lower() not in NON_AUDIO_SUFFIXES
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"Atteso un solo file audio in {job_dir}: trovati {len(candidates)}"
        )
    return candidates[0]


def _prepare_stage(
    job_dir: Path, progress: _Progress
) -> tuple[Path, Settings, JobRecord]:
    record = progress.store.get(job_id=progress.job_id)
    config = Settings.model_validate(
        {**settings.model_dump(), **record.config.model_dump()}
    )
    audio_path = _find_audio(job_dir=job_dir)
    logger.info("Avvio stage %s per il job %s", progress.stage, progress.job_id)
    return audio_path, config, record


def _execute_pipeline_stage(
    job_dir: Path, pipeline: StagePipeline | None, progress: _Progress
) -> None:
    audio_path, config, record = _prepare_stage(job_dir=job_dir, progress=progress)
    if progress.stage == JobStage.TRANSCRIBING:
        transcribe = pipeline if pipeline is not None else transcribe_to_dir
        json_path = transcribe(
            audio_path=audio_path,
            output_dir=job_dir,
            config=config,
            on_progress=progress,
        )
        # Downloads and headings carry the uploaded name, not audio.<ext>.
        if record.source_name and isinstance(json_path, Path):
            label_transcript(
                json_path=json_path, source_name=record.source_name, config=config
            )
        return
    json_path = audio_path.with_suffix(".json")
    if not json_path.is_file():
        raise FileNotFoundError(f"Trascrizione assente: {json_path}")
    correct = pipeline if pipeline is not None else correct_to_dir
    outcome = correct(
        json_path=json_path,
        config=config,
        subject=record.config.subject,
        on_progress=progress,
    )
    _check_outcome(outcome=outcome)


def _execute_stage(
    job_dir: Path, pipeline: StagePipeline | None, progress: _Progress
) -> None:
    if progress.stage != JobStage.STUDY:
        _execute_pipeline_stage(job_dir=job_dir, pipeline=pipeline, progress=progress)
        return
    record = progress.store.get(job_id=progress.job_id)
    config = Settings.model_validate(
        {**settings.model_dump(), **record.config.model_dump()}
    )
    study = pipeline if pipeline is not None else generate_study_files
    study(job_dir=job_dir, config=config, on_progress=progress)


def _execute_with_notices(
    job_dir: Path, pipeline: StagePipeline | None, progress: _Progress
) -> None:
    app_logger = logging.getLogger("sbobina")
    handler = _NoticeHandler(progress=progress)
    app_logger.addHandler(handler)
    try:
        _execute_stage(job_dir=job_dir, pipeline=pipeline, progress=progress)
    finally:
        app_logger.removeHandler(handler)


def _check_outcome(outcome: Path | CorrectionOutcome) -> None:
    if not isinstance(outcome, CorrectionOutcome):
        raise TypeError("Risultato della pipeline di correzione non valido")
    if outcome.interrupted:
        # correct_transcript sets interrupted_at only for CorrectorUnavailableError;
        # interrupted_error carries its message (chain causes, no keys) when the
        # engine is "api" and falls back to the historic text for Ollama-only runs.
        cause = outcome.result.interrupted_error
        reason = (
            str(cause)
            if isinstance(cause, ChainExhaustedError)
            else "Ollama irraggiungibile"
        )
        raise CorrectorUnavailableError(
            f"Correzione interrotta a {outcome.result.interrupted_at} s: {reason}"
        )


def _run_job_stage(
    stage: str, job_dir: Path, pipeline: StagePipeline | None, now: Callable[[], float]
) -> None:
    progress = _Progress(
        store=JobStore(data_dir=job_dir.parent.parent),
        job_id=job_dir.name,
        stage=STAGES[stage],
        now=now,
    )
    _execute_with_notices(job_dir=job_dir, pipeline=pipeline, progress=progress)
    progress.finish()


def run_stage(
    stage: str,
    job_dir: Path,
    *,
    pipeline: StagePipeline | None = None,
    now: Callable[[], float] = time.monotonic,
) -> int:
    """Run a stage and write progress; job state belongs to the supervisor.

    For "generation" job_dir is actually courses/<course_id>, and for "ocr"
    it is courses/<course_id>/documents/<doc_id>: neither has per-job
    progress to write (a single blocking call, no JobRecord), so both bypass
    _Progress entirely and persist their own result.
    """
    try:
        if stage == GENERATION_STAGE:
            run_generation_stage(course_dir=job_dir)
            return 0
        if stage == OCR_STAGE:
            run_ocr_stage(document_dir=job_dir)
            return 0
        _run_job_stage(stage=stage, job_dir=job_dir, pipeline=pipeline, now=now)
        return 0
    except CorrectorUnavailableError:
        logger.exception("Stage %s fallito per il job %s", stage, job_dir)
        ollama_stages = ("correct", "study", GENERATION_STAGE, OCR_STAGE)
        return OLLAMA_UNAVAILABLE_EXIT if stage in ollama_stages else 1
    except Exception:
        logger.exception("Stage %s fallito per il job %s", stage, job_dir)
        return 1


def _watch_stdin() -> None:
    try:
        while sys.stdin.readline() != "":
            pass
    except Exception:
        logger.exception(
            "Lettura stdin fallita nel watchdog del processo %s", os.getpid()
        )
    os._exit(1)


def start_stdin_watchdog() -> Thread:
    """Start a daemon that immediately exits the process with code 1 on stdin EOF."""
    thread = Thread(target=_watch_stdin, daemon=True, name="stdin-watchdog")
    thread.start()
    return thread


def main(argv: Sequence[str] | None = None) -> int:
    """Parse stage arguments, start the stdin watchdog and return the stage exit code."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    install_redaction(settings=settings)
    parser = argparse.ArgumentParser(description="Esegue uno stage di un job locale")
    parser.add_argument("stage", choices=(*STAGES, GENERATION_STAGE, OCR_STAGE))
    parser.add_argument("job_dir", type=Path)
    try:
        args = parser.parse_args(args=argv)
        start_stdin_watchdog()
        return run_stage(stage=args.stage, job_dir=args.job_dir)
    except SystemExit as error:
        if error.code == 0:
            return 0
        logger.exception("Argomenti non validi per stage_runner")
        return 1
    except Exception:
        logger.exception("Avvio di stage_runner fallito")
        return 1


if __name__ == "__main__":
    sys.exit(main())

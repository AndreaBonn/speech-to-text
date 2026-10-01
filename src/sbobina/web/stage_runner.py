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
from sbobina.pipeline import CorrectionOutcome, correct_to_dir, transcribe_to_dir
from sbobina.settings import Settings, settings
from sbobina.web.job_models import JobStage
from sbobina.web.job_store import JobStore

logger = logging.getLogger("sbobina")
PROGRESS_INTERVAL_S = 1.0
NON_AUDIO_SUFFIXES = frozenset({".part", ".json", ".md", ".tmp"})
STAGES = {"transcribe": JobStage.TRANSCRIBING, "correct": JobStage.CORRECTING}
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

    def __post_init__(self) -> None:
        self.started = self.now()

    def __call__(self, done: float, total: float) -> None:
        timestamp = self.now()
        if self.stage == JobStage.TRANSCRIBING:
            self.audio_s = max(0.0, float(done))
        if (
            self.last_write is not None
            and timestamp - self.last_write < PROGRESS_INTERVAL_S
        ):
            return
        fraction = min(1.0, max(0.0, done / total)) if total > 0 else 0.0
        self._write(fraction=fraction, timestamp=timestamp)

    def finish(self) -> None:
        self._write(fraction=1.0, timestamp=self.now())

    def _write(self, fraction: float, timestamp: float) -> None:
        self.store.write_progress(
            job_id=self.job_id,
            progress={
                "stage": self.stage.value,
                "progress": float(fraction),
                "audio_s": self.audio_s,
                "elapsed_s": max(0.0, timestamp - self.started),
            },
        )
        self.last_write = timestamp


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
) -> tuple[Path, Settings, str | None]:
    record = progress.store.get(job_id=progress.job_id)
    config = Settings.model_validate(
        {**settings.model_dump(), **record.config.model_dump()}
    )
    audio_path = _find_audio(job_dir=job_dir)
    logger.info("Avvio stage %s per il job %s", progress.stage, progress.job_id)
    return audio_path, config, record.config.subject


def _execute_stage(
    job_dir: Path, pipeline: StagePipeline | None, progress: _Progress
) -> None:
    audio_path, config, subject = _prepare_stage(job_dir=job_dir, progress=progress)
    if progress.stage == JobStage.TRANSCRIBING:
        transcribe = pipeline if pipeline is not None else transcribe_to_dir
        transcribe(
            audio_path=audio_path,
            output_dir=job_dir,
            config=config,
            on_progress=progress,
        )
        return
    json_path = audio_path.with_suffix(".json")
    if not json_path.is_file():
        raise FileNotFoundError(f"Trascrizione assente: {json_path}")
    correct = pipeline if pipeline is not None else correct_to_dir
    outcome = correct(
        json_path=json_path,
        config=config,
        subject=subject,
        on_progress=progress,
    )
    _check_outcome(outcome=outcome)


def _check_outcome(outcome: Path | CorrectionOutcome) -> None:
    if not isinstance(outcome, CorrectionOutcome):
        raise TypeError("Risultato della pipeline di correzione non valido")
    if outcome.interrupted:
        # correct_transcript sets interrupted_at only for CorrectorUnavailableError.
        raise CorrectorUnavailableError(
            f"Correzione interrotta a {outcome.result.interrupted_at} s: Ollama irraggiungibile"
        )


def run_stage(
    stage: str,
    job_dir: Path,
    *,
    pipeline: StagePipeline | None = None,
    now: Callable[[], float] = time.monotonic,
) -> int:
    """Run a stage without starting a watchdog; return exit code 0, 1 or 2.

    The runner only writes ``progress.json``: ``job.json`` is owned by the
    supervisor, which knows the child's pid and decides every status change.

    Parameters
    ----------
    stage, job_dir : str, Path
        ``transcribe`` or ``correct`` and the absolute job directory.
    pipeline : callable, optional
        Replacement for the selected stage's real pipeline, with its signature.
    now : callable
        Monotonic clock used for progress throttling and elapsed time.
    """
    try:
        progress = _Progress(
            store=JobStore(data_dir=job_dir.parent.parent),
            job_id=job_dir.name,
            stage=STAGES[stage],
            now=now,
        )
        _execute_stage(job_dir=job_dir, pipeline=pipeline, progress=progress)
        progress.finish()
        return 0
    except CorrectorUnavailableError:
        logger.exception(
            "Stage %s fallito per il job %s: Ollama irraggiungibile", stage, job_dir
        )
        return 2 if stage == "correct" else 1
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
    parser = argparse.ArgumentParser(description="Esegue uno stage di un job locale")
    parser.add_argument("stage", choices=tuple(STAGES))
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

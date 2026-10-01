import logging
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import make_segment, make_transcript, make_word

from sbobina.correction import CorrectionResult, CorrectorUnavailableError
from sbobina.models import load_transcript, save_transcript
from sbobina.notices import USER_NOTICE
from sbobina.pipeline import CorrectionOutcome
from sbobina.settings import Settings, settings
from sbobina.web import stage_runner
from sbobina.web.job_models import JobConfig
from sbobina.web.job_store import JobStore


@pytest.fixture
def job_dir(tmp_path: Path) -> Path:
    record = JobStore(data_dir=tmp_path).create(
        config=JobConfig(beam_size=3, subject="Fisica")
    )
    directory = tmp_path / "jobs" / str(record.id)
    for suffix in ("ogg", "json", "md", "corretto.json", "part"):
        (directory / f"audio.{suffix}").write_text("{}", encoding="utf-8")
    return directory


@pytest.mark.parametrize("callbacks", [True, False])
def test_run_stage_transcribe_writes_progress_and_leaves_job_record(
    job_dir: Path, callbacks: bool
) -> None:
    store = JobStore(data_dir=job_dir.parent.parent)
    # job.json belongs to the supervisor: a second writer could undo a cancel.
    record_before = store.get(job_id=job_dir.name)

    def transcribe(
        audio_path: Path,
        output_dir: Path,
        config: Settings,
        on_progress: Callable[[float, float], None],
    ) -> Path:
        assert audio_path == job_dir / "audio.ogg"
        assert output_dir == job_dir
        assert config.beam_size == 3
        assert config.ollama_host == settings.ollama_host
        assert store.get(job_id=job_dir.name) == record_before
        if callbacks:
            on_progress(2.0, 10.0)
            on_progress(8.0, 10.0)
        return output_dir / "audio.json"

    result = stage_runner.run_stage(
        stage="transcribe", job_dir=job_dir, pipeline=transcribe
    )

    assert result == 0
    progress = store.read_progress(job_id=job_dir.name)
    assert progress["progress"] == 1.0
    assert progress["stage"] == "transcribing"
    assert progress["audio_s"] == (8.0 if callbacks else 0.0)
    assert store.get(job_id=job_dir.name) == record_before


def test_run_stage_throttle_writes_once_per_second_and_forces_final(
    job_dir: Path,
) -> None:
    clock = iter([0.0, 0.0, 0.2, 1.0, 1.1])

    def transcribe(
        audio_path: Path,
        output_dir: Path,
        config: Settings,
        on_progress: Callable[[float, float], None],
    ) -> Path:
        on_progress(1.0, 10.0)
        on_progress(5.0, 10.0)
        on_progress(9.0, 10.0)
        return output_dir / "audio.json"

    with patch.object(JobStore, "write_progress", autospec=True) as write:
        result = stage_runner.run_stage(
            stage="transcribe",
            job_dir=job_dir,
            pipeline=transcribe,
            now=lambda: next(clock),
        )

    assert result == 0
    rows = [call.kwargs["progress"] for call in write.call_args_list]
    assert [row["progress"] for row in rows] == [0.1, 0.9, 1.0]
    assert [row["elapsed_s"] for row in rows] == [0.0, 1.0, 1.1]


@pytest.mark.parametrize(
    ("done", "total", "expected"), [(0, 0, 0.0), (-1, 2, 0.0), (3, 2, 1.0)]
)
def test_run_stage_progress_bounds_are_clamped(
    job_dir: Path,
    done: float,
    total: float,
    expected: float,
) -> None:
    def transcribe(
        audio_path: Path,
        output_dir: Path,
        config: Settings,
        on_progress: Callable[[float, float], None],
    ) -> Path:
        on_progress(done, total)
        return output_dir / "audio.json"

    with patch.object(JobStore, "write_progress", autospec=True) as write:
        result = stage_runner.run_stage(
            stage="transcribe", job_dir=job_dir, pipeline=transcribe
        )

    assert result == 0
    assert write.call_args_list[0].kwargs["progress"]["progress"] == expected
    assert write.call_args_list[-1].kwargs["progress"]["progress"] == 1.0


@pytest.fixture
def outcome(interrupted_at: float | None) -> CorrectionOutcome:
    transcript = make_transcript([make_segment([make_word(" ciao", 0.0)])])
    return CorrectionOutcome(
        result=CorrectionResult(
            transcript=transcript,
            applied=[],
            rejected=[],
            interrupted_at=interrupted_at,
        ),
        corrected_json=None,
    )


@pytest.mark.parametrize("interrupted_at", [None, 0.0, 5.0])
def test_run_stage_correct_outcome_sets_exit_and_progress(
    job_dir: Path,
    interrupted_at: float | None,
    outcome: CorrectionOutcome,
    caplog: pytest.LogCaptureFixture,
) -> None:

    def correct(
        json_path: Path,
        config: Settings,
        subject: str | None,
        on_progress: Callable[[int, int], None],
    ) -> CorrectionOutcome:
        assert json_path == job_dir / "audio.json"
        assert subject == "Fisica" and config.beam_size == 3
        on_progress(1, 4)
        return outcome

    result = stage_runner.run_stage(stage="correct", job_dir=job_dir, pipeline=correct)

    progress = JobStore(data_dir=job_dir.parent.parent).read_progress(
        job_id=job_dir.name
    )
    assert result == (0 if interrupted_at is None else 2)
    assert progress["progress"] == (1.0 if interrupted_at is None else 0.25)
    assert progress["audio_s"] == 0.0 and progress["stage"] == "correcting"
    assert bool(caplog.records) == (interrupted_at is not None)
    if interrupted_at is not None:
        assert caplog.records[-1].exc_info is not None


@pytest.mark.parametrize(
    "failure",
    [
        ("correct", CorrectorUnavailableError("offline"), 2),
        ("transcribe", CorrectorUnavailableError("offline"), 1),
        ("transcribe", RuntimeError("failed"), 1),
        ("correct", RuntimeError("failed"), 1),
    ],
)
def test_run_stage_pipeline_error_logs_traceback_and_returns_code(
    job_dir: Path,
    caplog: pytest.LogCaptureFixture,
    failure: tuple[str, Exception, int],
) -> None:
    stage, error, expected = failure
    with (
        patch.object(
            stage_runner, "transcribe_to_dir", side_effect=error
        ) as transcribe,
        patch.object(stage_runner, "correct_to_dir", side_effect=error) as correct,
    ):
        result = stage_runner.run_stage(stage=stage, job_dir=job_dir)

    assert (result, transcribe.call_count + correct.call_count) == (expected, 1)
    assert caplog.records[-1].exc_info is not None
    assert job_dir.name in caplog.records[-1].message
    assert (
        JobStore(data_dir=job_dir.parent.parent).read_progress(job_id=job_dir.name)
        == {}
    )


@pytest.mark.parametrize(
    "fault", ["missing", "ambiguous", "transcript", "settings", "stage", "record"]
)
def test_run_stage_invalid_input_returns_one_without_pipeline(
    job_dir: Path,
    fault: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    stage = "transcribe"
    if fault == "missing":
        (job_dir / "audio.ogg").unlink()
    elif fault == "ambiguous":
        (job_dir / "audio.wav").touch()
    elif fault == "transcript":
        stage = "correct"
        (job_dir / "audio.json").unlink()
    elif fault == "record":
        (job_dir / "job.json").write_text("broken", encoding="utf-8")
    elif fault == "stage":
        stage = "unknown"
    base = (
        settings.model_copy(update={"cpu_threads": -1})
        if fault == "settings"
        else settings
    )
    with (
        patch.object(stage_runner, "settings", base),
        patch.object(stage_runner, "transcribe_to_dir") as pipeline,
    ):
        result = stage_runner.run_stage(stage, job_dir)
    assert result == 1
    pipeline.assert_not_called()
    assert caplog.records[-1].exc_info is not None


@pytest.mark.parametrize("exit_code", [0, 1, 2])
def test_main_starts_watchdog_before_running_stage(
    job_dir: Path, exit_code: int
) -> None:
    with patch.object(stage_runner, "start_stdin_watchdog") as start:

        def run(stage: str, job_dir: Path) -> int:
            start.assert_called_once_with()
            assert stage == "correct"
            return exit_code

        with patch.object(stage_runner, "run_stage", side_effect=run) as runner:
            assert stage_runner.main(argv=["correct", str(job_dir)]) == exit_code
    runner.assert_called_once_with(stage="correct", job_dir=job_dir)


@pytest.mark.parametrize(
    ("args", "expected"), [([], 1), (["unknown", "/tmp/job"], 1), (["--help"], 0)]
)
def test_main_invalid_arguments_and_help_skip_stage(
    args: list[str], expected: int
) -> None:
    with patch.object(stage_runner, "run_stage") as runner:
        assert stage_runner.main(argv=args) == expected
    runner.assert_not_called()


@pytest.fixture
def watchdog_script(tmp_path: Path, close_stdin: bool) -> Path:
    script = tmp_path / "watchdog_child.py"
    script.write_text(
        "import sys\nfrom threading import Event\n"
        "from sbobina.web.stage_runner import start_stdin_watchdog\n"
        "thread = start_stdin_watchdog()\nassert thread.daemon\n"
        "sys.stdout.write('ready\\n'); sys.stdout.flush()\n"
        + ("Event().wait()\n" if close_stdin else ""),
        encoding="utf-8",
    )
    return script


@pytest.mark.parametrize("close_stdin", [True, False])
def test_start_stdin_watchdog_real_child_exits_on_eof_or_normal_completion(
    watchdog_script: Path,
    close_stdin: bool,
) -> None:
    with subprocess.Popen(
        [sys.executable, "-u", str(watchdog_script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    ) as process:
        try:
            assert process.stdin is not None and process.stdout is not None
            process.stdin.write("heartbeat\n")
            process.stdin.flush()
            assert process.stdout.readline() == "ready\n"
            if close_stdin:
                process.stdin.close()
            assert process.wait(timeout=2) == (1 if close_stdin else 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)


def test_module_entrypoint_runs_stage_and_reports_failure(job_dir: Path) -> None:
    # stdin stays open like under the supervisor; audio.json in the fixture is
    # "{}", so the real correct pipeline fails to load it.
    child = subprocess.Popen(
        [sys.executable, "-m", "sbobina.web.stage_runner", "correct", str(job_dir)],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        returncode = child.wait(timeout=60)
    finally:
        assert child.stdin is not None and child.stderr is not None
        child.stdin.close()
        stderr = child.stderr.read()
        child.stderr.close()

    assert returncode == 1
    assert "Stage correct fallito" in stderr
    assert (
        JobStore(data_dir=job_dir.parent.parent).read_progress(job_id=job_dir.name)
        == {}
    )


def test_run_stage_user_notice_from_pipeline_reaches_progress(job_dir: Path) -> None:
    store = JobStore(data_dir=job_dir.parent.parent)

    def transcribe(
        audio_path: Path,
        output_dir: Path,
        config: Settings,
        on_progress: Callable[[float, float], None],
    ) -> Path:
        logging.getLogger("sbobina.transcriber").warning(
            "GPU non utilizzabile", extra={USER_NOTICE: True}
        )
        logging.getLogger("sbobina.transcriber").warning("solo per il log")
        return output_dir / "audio.json"

    assert (
        stage_runner.run_stage(stage="transcribe", job_dir=job_dir, pipeline=transcribe)
        == 0
    )

    assert store.read_progress(job_id=job_dir.name)["notice"] == "GPU non utilizzabile"


def test_run_stage_transcribe_labels_output_with_uploaded_name(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    record = store.create(config=JobConfig(), source_name="Lezione 3.m4a")
    directory = store.jobs_dir / str(record.id)
    (directory / "audio.m4a").write_bytes(b"x")

    def transcribe(
        audio_path: Path,
        output_dir: Path,
        config: Settings,
        on_progress: Callable[[float, float], None],
    ) -> Path:
        json_path = output_dir / "audio.json"
        transcript = make_transcript([make_segment([make_word(" ciao", 0.0, 0.5)])])
        save_transcript(replace(transcript, source=str(audio_path)), json_path)
        return json_path

    result = stage_runner.run_stage(
        stage="transcribe", job_dir=directory, pipeline=transcribe
    )

    assert result == 0
    assert load_transcript(directory / "audio.json").source == "Lezione 3.m4a"
    heading = (directory / "audio.md").read_text(encoding="utf-8").splitlines()[0]
    assert heading == "# Sbobinatura: Lezione 3.m4a"

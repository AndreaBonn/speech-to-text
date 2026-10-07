from pathlib import Path

import pytest

from sbobina.ollama_embed import EmbeddingUnavailableError
from sbobina.web import stage_runner


def test_embed_stage_dispatches_course_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Path] = []
    monkeypatch.setattr(
        stage_runner, "run_embed_stage", lambda course_dir: seen.append(course_dir)
    )
    assert stage_runner.run_stage(stage="embed", job_dir=tmp_path) == 0
    assert seen == [tmp_path]


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (EmbeddingUnavailableError(reason="unreachable"), 2),
        (RuntimeError("broken"), 1),
    ],
)
def test_embed_stage_maps_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    code: int,
) -> None:
    def fail(course_dir: Path) -> None:
        raise error

    monkeypatch.setattr(stage_runner, "run_embed_stage", fail)
    assert stage_runner.run_stage(stage="embed", job_dir=tmp_path) == code


def test_embed_cli_accepts_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        stage_runner, "start_stdin_watchdog", lambda: calls.append("watchdog")
    )
    monkeypatch.setattr(
        stage_runner, "run_embed_stage", lambda course_dir: calls.append("embed")
    )
    assert stage_runner.main(argv=["embed", str(tmp_path)]) == 0
    assert calls == ["watchdog", "embed"]

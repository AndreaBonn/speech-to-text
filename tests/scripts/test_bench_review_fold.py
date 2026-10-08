import json
import runpy
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bench_review_fold.py"
SMALL_CARDS = 20
SMALL_REVIEWS = 100
SMALL_RUNS = 3


def run_bench(extra_args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        check=True,
        args=[
            sys.executable,
            str(SCRIPT),
            "--cards",
            str(SMALL_CARDS),
            "--reviews",
            str(SMALL_REVIEWS),
            "--runs",
            str(SMALL_RUNS),
            *extra_args,
        ],
        capture_output=True,
        text=True,
    )


def test_main_json_reports_runs_and_fold_append_timings() -> None:
    result = run_bench(extra_args=["--json"])
    report = json.loads(result.stdout)

    assert report["runs"] == SMALL_RUNS
    for section in ("fold", "append"):
        assert set(report[section]) == {"p50_ms", "max_ms"}
        assert report[section]["p50_ms"] >= 0.0
        assert report[section]["max_ms"] >= report[section]["p50_ms"]


def test_main_text_mode_prints_fold_and_append_lines() -> None:
    result = run_bench(extra_args=[])

    assert f"runs: {SMALL_RUNS}" in result.stdout
    assert "fold (load_cards)" in result.stdout
    assert "append (reviews.jsonl)" in result.stdout


def test_run_benchmark_leaves_no_temporary_directory_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A private temp root: the shared system one may hold other runs' dirs.
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    created: list[str] = []
    real_temporary_directory = tempfile.TemporaryDirectory

    def tracking_temporary_directory(**kwargs: Any) -> Any:
        directory = real_temporary_directory(**kwargs)
        created.append(directory.name)
        return directory

    monkeypatch.setattr(tempfile, "TemporaryDirectory", tracking_temporary_directory)
    run_benchmark = runpy.run_path(path_name=str(SCRIPT))["run_benchmark"]

    report = run_benchmark(
        num_cards=SMALL_CARDS, num_reviews=SMALL_REVIEWS, runs=SMALL_RUNS
    )

    assert report.runs == SMALL_RUNS
    assert [Path(name).parent for name in created] == [tmp_path]
    assert list(tmp_path.iterdir()) == []

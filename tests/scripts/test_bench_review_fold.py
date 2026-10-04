import json
import runpy
import subprocess
import sys
import tempfile
from pathlib import Path

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


def test_run_benchmark_leaves_no_temporary_directory_behind() -> None:
    system_tmp = Path(tempfile.gettempdir())
    run_benchmark = runpy.run_path(path_name=str(SCRIPT))["run_benchmark"]
    before = sorted(system_tmp.glob("bench-review-fold-*"))

    report = run_benchmark(
        num_cards=SMALL_CARDS, num_reviews=SMALL_REVIEWS, runs=SMALL_RUNS
    )

    assert report.runs == SMALL_RUNS
    assert sorted(system_tmp.glob("bench-review-fold-*")) == before

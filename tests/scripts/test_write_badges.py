import json
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "write_badges.py"


def write_junit(
    path: Path, tests: int, failures: int = 0, errors: int = 0, skipped: int = 0
) -> None:
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites>'
        f'<testsuite name="pytest" tests="{tests}" failures="{failures}" '
        f'errors="{errors}" skipped="{skipped}"></testsuite></testsuites>',
        encoding="utf-8",
    )


def write_coverage(path: Path, percent: float) -> None:
    path.write_text(
        json.dumps({"totals": {"percent_covered": percent}}), encoding="utf-8"
    )


def load(name: str) -> Any:
    return runpy.run_path(path_name=str(SCRIPT))[name]


def test_tests_badge_all_green_counts_passed_without_skipped(tmp_path: Path) -> None:
    junit = tmp_path / "junit.xml"
    write_junit(path=junit, tests=12, skipped=2)

    badge = load("tests_badge")(junit_path=junit)

    assert badge == {
        "schemaVersion": 1,
        "label": "tests",
        "message": "10 passed",
        "color": "brightgreen",
    }


def test_tests_badge_failures_and_errors_turn_red(tmp_path: Path) -> None:
    junit = tmp_path / "junit.xml"
    write_junit(path=junit, tests=10, failures=2, errors=1)

    badge = load("tests_badge")(junit_path=junit)

    assert badge["message"] == "3 failed, 7 passed"
    assert badge["color"] == "red"


def test_tests_badge_without_testsuite_is_rejected(tmp_path: Path) -> None:
    junit = tmp_path / "junit.xml"
    junit.write_text("<testsuites></testsuites>", encoding="utf-8")

    with pytest.raises(ValueError, match="testsuite"):
        load("tests_badge")(junit_path=junit)


@pytest.mark.parametrize(
    ("percent", "message", "color"),
    [
        (99.68, "99%", "brightgreen"),
        (90.0, "90%", "brightgreen"),
        (85.5, "85%", "green"),
        (72.0, "72%", "yellow"),
        (61.0, "61%", "orange"),
        (12.0, "12%", "red"),
    ],
)
def test_coverage_badge_truncates_percent_and_picks_color(
    tmp_path: Path, percent: float, message: str, color: str
) -> None:
    report = tmp_path / "coverage.json"
    write_coverage(path=report, percent=percent)

    badge = load("coverage_badge")(coverage_path=report)

    assert badge == {
        "schemaVersion": 1,
        "label": "coverage",
        "message": message,
        "color": color,
    }


def test_main_writes_both_badges_into_a_new_directory(tmp_path: Path) -> None:
    junit = tmp_path / "junit.xml"
    report = tmp_path / "coverage.json"
    write_junit(path=junit, tests=3)
    write_coverage(path=report, percent=99.7)
    out = tmp_path / "badges"

    subprocess.run(
        args=[
            sys.executable,
            str(SCRIPT),
            "--junit",
            str(junit),
            "--coverage",
            str(report),
            "--out",
            str(out),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads((out / "test-badge.json").read_text())["message"] == "3 passed"
    assert json.loads((out / "coverage-badge.json").read_text())["message"] == "99%"


def test_main_missing_report_fails_without_writing(tmp_path: Path) -> None:
    out = tmp_path / "badges"

    result = subprocess.run(
        args=[
            sys.executable,
            str(SCRIPT),
            "--junit",
            str(tmp_path / "missing.xml"),
            "--coverage",
            str(tmp_path / "missing.json"),
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "missing.xml" in result.stderr
    assert not out.exists()


def test_main_missing_coverage_with_valid_junit_writes_nothing(tmp_path: Path) -> None:
    junit = tmp_path / "junit.xml"
    write_junit(path=junit, tests=3)
    out = tmp_path / "badges"

    result = subprocess.run(
        args=[
            sys.executable,
            str(SCRIPT),
            "--junit",
            str(junit),
            "--coverage",
            str(tmp_path / "missing.json"),
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "missing.json" in result.stderr
    assert not out.exists()

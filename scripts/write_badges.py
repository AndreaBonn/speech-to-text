"""Write shields.io endpoint badges for the test count and the coverage.

Reads the JUnit XML that `pytest --junitxml` writes and the JSON report of
`pytest --cov-report=json`, then writes `test-badge.json` and
`coverage-badge.json` in the shields.io endpoint schema
(https://shields.io/badges/endpoint-badge). Both reports are read before any
file is written, so a missing report leaves the output directory untouched.
"""

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

SCHEMA_VERSION = 1
TEST_BADGE_FILENAME = "test-badge.json"
COVERAGE_BADGE_FILENAME = "coverage-badge.json"
# Lowest percent for each color, checked from the top down.
COVERAGE_COLORS = ((90, "brightgreen"), (80, "green"), (70, "yellow"), (60, "orange"))
LOW_COVERAGE_COLOR = "red"


def _badge(label: str, message: str, color: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "label": label,
        "message": message,
        "color": color,
    }


def tests_badge(junit_path: Path) -> dict[str, Any]:
    """Count passed tests (skipped excluded); any failure or error turns it red."""
    suites = ElementTree.parse(source=junit_path).getroot().iter(tag="testsuite")
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    found = False
    for suite in suites:
        found = True
        for key in totals:
            totals[key] += int(suite.get(key=key, default="0"))
    if not found:
        raise ValueError(f"No testsuite element in {junit_path}")
    broken = totals["failures"] + totals["errors"]
    passed = totals["tests"] - broken - totals["skipped"]
    if broken:
        return _badge(
            label="tests", message=f"{broken} failed, {passed} passed", color="red"
        )
    return _badge(label="tests", message=f"{passed} passed", color="brightgreen")


def coverage_badge(coverage_path: Path) -> dict[str, Any]:
    """Whole-number percent, truncated so 99.7% never reads as 100%."""
    # totals.percent_covered merges lines and branches when --cov-branch is on:
    # https://github.com/coveragepy/coveragepy/blob/main/doc/faq.rst
    report = json.loads(coverage_path.read_text(encoding="utf-8"))
    percent = math.floor(float(report["totals"]["percent_covered"]))
    color = next(
        (name for floor, name in COVERAGE_COLORS if percent >= floor),
        LOW_COVERAGE_COLOR,
    )
    return _badge(label="coverage", message=f"{percent}%", color=color)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(args=argv)
    try:
        badges = {
            TEST_BADGE_FILENAME: tests_badge(junit_path=args.junit),
            COVERAGE_BADGE_FILENAME: coverage_badge(coverage_path=args.coverage),
        }
    except (OSError, ValueError, KeyError, ElementTree.ParseError) as error:
        print(f"write_badges: {error}", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    for filename, badge in badges.items():
        (args.out / filename).write_text(json.dumps(badge) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

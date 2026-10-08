"""Runs the node:test suites for the pure browser helpers in tests/js."""

import shutil
import subprocess
from pathlib import Path

import pytest

JS_TESTS_DIR = Path(__file__).resolve().parent.parent / "js"
NODE_TIMEOUT_S = 60


@pytest.mark.skipif(shutil.which("node") is None, reason="node non installato")
def test_js_unit_suites_pass() -> None:
    suites = sorted(str(path) for path in JS_TESTS_DIR.glob("*.test.mjs"))
    assert suites, "nessuna suite in tests/js"

    result = subprocess.run(
        ["node", "--test", *suites],
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_S,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr

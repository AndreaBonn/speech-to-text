import sys

import pytest

from sbobina.web.processes import _child_env


def test_child_env_preserves_environment_and_enables_windows_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SB0BINA_TEST_ENV", "preserved")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    environment = _child_env()
    assert environment["SB0BINA_TEST_ENV"] == "preserved"
    assert environment["PYTHONUTF8"] == "1"

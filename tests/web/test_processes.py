import signal
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from sbobina.web.processes import _child_env, _reap, _spawn

WINDOWS_NEW_GROUP = 0x200


def test_child_env_preserves_environment_and_enables_windows_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SB0BINA_TEST_ENV", "preserved")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    environment = _child_env()
    assert environment["SB0BINA_TEST_ENV"] == "preserved"
    assert environment["PYTHONUTF8"] == "1"


class _PopenRecorder:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] = {}

    def __call__(self, **kwargs: object) -> str:
        self.kwargs = kwargs
        return "child"


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("win32", {"creationflags": WINDOWS_NEW_GROUP}),
        ("linux", {"start_new_session": True}),
    ],
)
def test_spawn_detaches_the_child_the_way_each_platform_supports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    expected: dict[str, object],
) -> None:
    recorder = _PopenRecorder()
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(subprocess, "Popen", recorder)
    monkeypatch.setattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", WINDOWS_NEW_GROUP, raising=False
    )

    child = _spawn(command=["runner"], log_path=tmp_path / "child.log")

    detach_keys = {"creationflags", "start_new_session"}
    detach = {k: v for k, v in recorder.kwargs.items() if k in detach_keys}
    assert cast(object, child) == "child"
    assert detach == expected
    assert recorder.kwargs["stdin"] is subprocess.PIPE


@pytest.mark.parametrize("graceful", [True, False])
def test_reap_child_without_stdin_is_terminated(graceful: bool) -> None:
    process = subprocess.Popen(
        args=[sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=None,
    )

    _reap(process=process, timeout_s=5, graceful=graceful)

    assert process.returncode == -signal.SIGTERM

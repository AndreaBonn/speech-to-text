import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("sbobina")


def _child_env() -> dict[str, str]:
    # Force UTF-8 I/O in the child: a Windows pipe/file otherwise uses the
    # system codepage and raises UnicodeEncodeError on accented log text
    # (BASIS: inferred).
    env = dict(os.environ)
    if sys.platform == "win32":
        env["PYTHONUTF8"] = "1"
    return env


def _spawn(command: list[str], log_path: Path) -> subprocess.Popen[bytes]:
    # Redirected to a file, never piped: a pipe nobody drains blocks the
    # child once its OS buffer fills.
    with log_path.open("a", encoding="utf-8") as log_file:
        if sys.platform == "win32":
            return subprocess.Popen(
                args=command,
                stdin=subprocess.PIPE,
                stdout=log_file,
                stderr=log_file,
                env=_child_env(),
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        return subprocess.Popen(
            args=command,
            stdin=subprocess.PIPE,
            stdout=log_file,
            stderr=log_file,
            env=_child_env(),
            start_new_session=True,
        )


def _reap(process: subprocess.Popen[bytes], timeout_s: float, graceful: bool) -> None:
    try:
        if graceful and process.stdin is not None:
            process.stdin.close()
            try:
                process.wait(timeout=timeout_s)
                return
            except subprocess.TimeoutExpired:
                logger.info(
                    "Il processo %s non si è fermato alla chiusura stdin", process.pid
                )
        process.terminate()
        try:
            process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            logger.warning("Arresto forzato del processo %s", process.pid)
            process.kill()
            process.wait()
    finally:
        if process.stdin is not None:
            process.stdin.close()

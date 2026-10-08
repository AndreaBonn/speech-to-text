import signal

from sbobina.web.package_import_worker import MEMORY_EXIT_CODE, memory_exit_codes


def test_memory_exit_codes_posix_includes_kernel_kill() -> None:
    assert memory_exit_codes(platform="linux") == {MEMORY_EXIT_CODE, -signal.SIGKILL}


def test_memory_exit_codes_windows_only_runner_code() -> None:
    # Windows has no signal.SIGKILL: evaluating it at import crashed startup.
    assert memory_exit_codes(platform="win32") == {MEMORY_EXIT_CODE}

import fcntl
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sbobina.web import vector_schema


def _can_share(path: Path) -> bool:
    """True if another open file description can take a shared lock right now."""
    with path.with_suffix(".lock").open(mode="a+b") as probe:
        try:
            fcntl.flock(probe.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
        return True


def test_file_lock_posix_shared_admits_other_readers(tmp_path: Path) -> None:
    path = tmp_path / "vectors.sqlite3"
    with vector_schema.file_lock(path=path, is_exclusive=False):
        assert _can_share(path) is True


def test_file_lock_posix_exclusive_blocks_readers(tmp_path: Path) -> None:
    path = tmp_path / "vectors.sqlite3"
    with vector_schema.file_lock(path=path, is_exclusive=True):
        assert _can_share(path) is False
    assert _can_share(path) is True


@pytest.mark.parametrize("is_exclusive", [False, True])
def test_file_lock_windows_is_always_exclusive(
    tmp_path: Path, is_exclusive: bool
) -> None:
    # filelock's Windows backend is msvcrt, which has no shared mode; on this
    # host the same class falls back to flock, so exclusivity stays observable.
    path = tmp_path / "vectors.sqlite3"
    with (
        patch.object(vector_schema, "sys", SimpleNamespace(platform="win32")),
        vector_schema.file_lock(path=path, is_exclusive=is_exclusive),
    ):
        assert _can_share(path) is False
    assert _can_share(path) is True

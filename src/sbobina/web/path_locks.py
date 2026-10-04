"""Process-local locks shared by file-backed stores."""

from pathlib import Path
from threading import Lock

_LOCKS_GUARD = Lock()
_PATH_LOCKS: dict[Path, Lock] = {}


def lock_for(path: Path) -> Lock:
    with _LOCKS_GUARD:
        lock = _PATH_LOCKS.get(path)
        if lock is None:
            lock = Lock()
            _PATH_LOCKS[path] = lock
        return lock

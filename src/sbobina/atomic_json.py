"""Atomic, symlink-safe JSON writes for small config files (D4).

Shared by `credential_store.py` and `user_preferences.py`: both write a small
JSON document into the same user config directory and need the same
guarantee an interrupted write (crash, raised exception) leaves the
previous file untouched. `Path.write_text` followed by `chmod` does not
give that: between the two calls the file exists with whatever mode the
umask produced.
"""

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4


class SymlinkTargetError(ValueError):
    """Refused to write through a symlink at the destination path."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"{path} è un symlink: scrittura rifiutata")


def atomic_write_json(path: Path, data: dict[str, Any], mode: int) -> None:
    """Write `data` as JSON to `path` via a temp file, then `os.replace`.

    Parameters
    ----------
    path : Path
        Destination file. Rejected outright if it is itself a symlink: a
        replace would unlink the link rather than write through it, but an
        explicit refusal is cheaper to reason about than relying on that.
    data : dict[str, Any]
        JSON-serializable content.
    mode : int
        Permission bits for the temp file, and so for the destination
        after the rename (e.g. ``0o600``).
    """
    if path.is_symlink():
        raise SymlinkTargetError(path)
    tmp_path = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)

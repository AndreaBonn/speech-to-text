"""Parse a file once per version and reuse the result across readers (F12).

Resolving 30 citations of an attempt read and parsed the same two transcripts
60 times (810 ms). The key is the file's identity and version (inode, mtime,
size) plus the parser, so a saved transcript (save_transcript replaces the
file, giving it a new inode) is read again and each caller keeps its own
parser and error behaviour. Version and text come from the same open file, so
a rename in between cannot pair new text with the old key. Errors are never
cached.
"""

import os
import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable
from pathlib import Path
from typing import Any

# Two lectures per citation set, three parsers each; a few spare.
MAX_ENTRIES = 16

_CACHE: OrderedDict[Hashable, Any] = OrderedDict()
_LOCK = threading.Lock()


def _cached(key: Hashable) -> tuple[bool, Any]:
    with _LOCK:
        if key not in _CACHE:
            return False, None
        _CACHE.move_to_end(key)
        return True, _CACHE[key]


def _store(key: Hashable, value: Any) -> None:
    with _LOCK:
        _CACHE[key] = value
        while len(_CACHE) > MAX_ENTRIES:
            _CACHE.popitem(last=False)


def read_parsed[T](path: Path, parse: Callable[[str], T]) -> T:
    """parse(file text), reused while the file keeps the same version."""
    with path.open(encoding="utf-8") as stream:
        stat = os.fstat(stream.fileno())
        key = (str(path), stat.st_ino, stat.st_mtime_ns, stat.st_size, parse)
        found, value = _cached(key=key)
        if found:
            cached: T = value
            return cached
        content = stream.read()
    result = parse(content)
    _store(key=key, value=result)
    return result

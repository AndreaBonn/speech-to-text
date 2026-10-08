import os
from collections.abc import Callable
from pathlib import Path

import pytest

from sbobina.file_cache import read_parsed


def _counting_parser() -> tuple[list[str], Callable[[str], str]]:
    calls: list[str] = []

    def parse(content: str) -> str:
        calls.append(content)
        return content.upper()

    return calls, parse


def test_read_parsed_same_file_parses_once(tmp_path: Path) -> None:
    path = tmp_path / "audio.json"
    path.write_text(data="primo", encoding="utf-8")
    calls, parse = _counting_parser()

    first = read_parsed(path=path, parse=parse)
    second = read_parsed(path=path, parse=parse)

    assert first == second == "PRIMO"
    assert calls == ["primo"]


def test_read_parsed_changed_file_is_read_again(tmp_path: Path) -> None:
    # A saved correction must never be served from the old parse.
    path = tmp_path / "audio.json"
    path.write_text(data="primo", encoding="utf-8")
    calls, parse = _counting_parser()
    read_parsed(path=path, parse=parse)

    path.write_text(data="secondo testo", encoding="utf-8")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    assert read_parsed(path=path, parse=parse) == "SECONDO TESTO"
    assert calls == ["primo", "secondo testo"]


def test_read_parsed_parsers_do_not_share_results(tmp_path: Path) -> None:
    path = tmp_path / "audio.json"
    path.write_text(data="testo", encoding="utf-8")

    assert read_parsed(path=path, parse=str.upper) == "TESTO"
    assert read_parsed(path=path, parse=len) == 5


def test_read_parsed_errors_propagate_and_are_not_cached(tmp_path: Path) -> None:
    path = tmp_path / "audio.json"
    path.write_text(data="x", encoding="utf-8")
    attempts: list[int] = []

    def failing(content: str) -> str:
        attempts.append(1)
        raise ValueError("bad transcript")

    for _ in range(2):
        with pytest.raises(ValueError):
            read_parsed(path=path, parse=failing)
    assert len(attempts) == 2


def test_read_parsed_missing_file_propagates_file_not_found(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"

    with pytest.raises(FileNotFoundError):
        read_parsed(path=path, parse=str.upper)

    path.write_text(data="present", encoding="utf-8")
    assert read_parsed(path=path, parse=str.upper) == "PRESENT"


def test_read_parsed_version_and_text_come_from_the_same_open_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # F12 review: a rename between the version check and the read must not
    # store the new text under the old file's key.
    path = tmp_path / "audio.json"
    path.write_text(data="vecchio", encoding="utf-8")
    replacement = tmp_path / "next.json"
    replacement.write_text(data="nuovo!!", encoding="utf-8")
    real_fstat = os.fstat
    swapped: list[bool] = []

    def fstat_then_swap(fd: int) -> os.stat_result:
        result = real_fstat(fd)
        if not swapped:
            os.replace(replacement, path)
            swapped.append(True)
        return result

    monkeypatch.setattr(os, "fstat", fstat_then_swap)

    assert read_parsed(path=path, parse=str.strip) == "vecchio"
    assert swapped == [True]
    assert read_parsed(path=path, parse=str.strip) == "nuovo!!"

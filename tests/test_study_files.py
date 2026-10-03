import os
from pathlib import Path

import pytest

from sbobina.study_files import atomic_write_pair


def _fail_replacing(target: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the move of a staged file onto `target` fail, as a full disk would."""
    real_replace = os.replace

    def replace(src: Path, dst: Path) -> None:
        if Path(dst) == target and Path(src).suffix == ".tmp":
            raise OSError("disk full")
        real_replace(src, dst)

    monkeypatch.setattr("sbobina.study_files.os.replace", replace)


def test_atomic_write_pair_writes_every_file_creating_parents(tmp_path: Path) -> None:
    first = tmp_path / "a" / "uno.md"
    second = tmp_path / "b" / "due.json"

    atomic_write_pair(contents={first: "primo è", second: "secondo"})

    assert first.read_text(encoding="utf-8") == "primo è"
    assert second.read_text(encoding="utf-8") == "secondo"


def test_atomic_write_pair_replaces_existing_content(tmp_path: Path) -> None:
    target = tmp_path / "file.md"
    target.write_text("vecchio", encoding="utf-8")

    atomic_write_pair(contents={target: "nuovo"})

    assert target.read_text(encoding="utf-8") == "nuovo"


def test_atomic_write_pair_failure_restores_replaced_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "uno.md"
    second = tmp_path / "due.json"
    first.write_text("uno originale", encoding="utf-8")
    second.write_text("due originale", encoding="utf-8")
    _fail_replacing(target=second, monkeypatch=monkeypatch)

    with pytest.raises(OSError, match="disk full"):
        atomic_write_pair(contents={first: "uno nuovo", second: "due nuovo"})

    assert first.read_text(encoding="utf-8") == "uno originale"
    assert second.read_text(encoding="utf-8") == "due originale"


def test_atomic_write_pair_failure_removes_file_that_did_not_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tmp_path / "nuovo.md"
    second = tmp_path / "due.json"
    second.write_text("due originale", encoding="utf-8")
    _fail_replacing(target=second, monkeypatch=monkeypatch)

    with pytest.raises(OSError):
        atomic_write_pair(contents={created: "contenuto", second: "due nuovo"})

    assert sorted(p.name for p in tmp_path.iterdir()) == ["due.json"]


def test_atomic_write_pair_leaves_no_staged_files(tmp_path: Path) -> None:
    target = tmp_path / "file.md"
    target.write_text("vecchio", encoding="utf-8")

    atomic_write_pair(contents={target: "nuovo", tmp_path / "altro.md": "x"})

    assert sorted(p.name for p in tmp_path.iterdir()) == ["altro.md", "file.md"]

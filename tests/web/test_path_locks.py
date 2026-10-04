from pathlib import Path

from sbobina.web.path_locks import lock_for


def test_lock_for_same_path_returns_same_lock_and_other_path_a_new_one(
    tmp_path: Path,
) -> None:
    first = lock_for(path=tmp_path / "a.jsonl")

    assert lock_for(path=tmp_path / "a.jsonl") is first
    assert lock_for(path=tmp_path / "b.jsonl") is not first

import os
from contextlib import ExitStack
from pathlib import Path
from tempfile import NamedTemporaryFile


def _stage_file(path: Path, content: bytes, cleanup: ExitStack) -> Path:
    with NamedTemporaryFile(
        mode="wb", dir=path.parent, suffix=".tmp", delete=False
    ) as temporary:
        staged = Path(temporary.name)
        cleanup.callback(staged.unlink, missing_ok=True)
        temporary.write(content)
    return staged


def _stage_outputs(
    contents: dict[Path, str], cleanup: ExitStack
) -> dict[Path, tuple[Path, Path | None]]:
    staged = {}
    for path, content in contents.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        backup = (
            _stage_file(path=path, content=path.read_bytes(), cleanup=cleanup)
            if path.exists()
            else None
        )
        temporary = _stage_file(
            path=path, content=content.encode("utf-8"), cleanup=cleanup
        )
        staged[path] = (temporary, backup)
    return staged


def atomic_write_pair(contents: dict[Path, str]) -> None:
    """Replace complete files; restore prior files after a recoverable write error."""
    with ExitStack() as cleanup:
        staged = _stage_outputs(contents=contents, cleanup=cleanup)
        replaced: list[Path] = []
        try:
            for path, (temporary, _) in staged.items():
                os.replace(temporary, path)
                replaced.append(path)
        except BaseException:
            for path in reversed(replaced):
                backup = staged[path][1]
                if backup is None:
                    path.unlink(missing_ok=True)
                else:
                    os.replace(backup, path)
            raise

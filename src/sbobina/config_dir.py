"""Resolves the per-user config directory for secrets and preferences (D1, D4).

Separate from `data_dir` (course data: copied, shared, exported) and from
the repository checkout: either would leak API keys or the cloud chain
preference into a course backup or a git clone. `resolve_config_dir` rejects
a resolved path under either, as a test rather than a convention.
"""

import os
import sys
from pathlib import Path

from sbobina.settings import Settings

_WINDOWS = "win32"
_MACOS = "darwin"
_APPDATA_ENV = "APPDATA"
_XDG_CONFIG_HOME_ENV = "XDG_CONFIG_HOME"
_CONFIG_DIR_NAME = "sbobina"
_CONFIG_DIR_MODE = 0o700


class ConfigDirUnsafeError(ValueError):
    """The resolved config directory would sit under `data_dir` or the repo."""

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"Cartella di configurazione non sicura ({reason}): {path}")


def _repo_root() -> Path | None:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return None


def _is_under_or_equal(path: Path, ancestor: Path) -> bool:
    return path == ancestor or ancestor in path.parents


def _default_dir() -> Path:
    if sys.platform == _WINDOWS:
        appdata = os.environ.get(_APPDATA_ENV)
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / _CONFIG_DIR_NAME
    if sys.platform == _MACOS:
        return Path.home() / "Library" / "Application Support" / _CONFIG_DIR_NAME
    xdg = os.environ.get(_XDG_CONFIG_HOME_ENV)
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / _CONFIG_DIR_NAME


def _candidate_path(settings: Settings) -> Path:
    if settings.config_dir is not None:
        return settings.config_dir
    return _default_dir()


def _reject_unsafe(path: Path, settings: Settings) -> None:
    resolved = path.resolve()
    data_dir = settings.data_dir.resolve()
    if _is_under_or_equal(resolved, data_dir):
        raise ConfigDirUnsafeError(path, reason="sotto data_dir")
    repo_root = _repo_root()
    if repo_root is not None and _is_under_or_equal(resolved, repo_root):
        raise ConfigDirUnsafeError(path, reason="sotto la root del repository")


def resolve_config_dir(settings: Settings, *, create: bool = True) -> Path:
    """Resolve the per-user config directory for secrets and preferences.

    Parameters
    ----------
    settings : Settings
        Source of the `config_dir` override and of `data_dir` for the
        safety check against it.
    create : bool
        When true (the default), create the directory with mode 0700 if it
        is missing. Read-only callers (log redaction, probing for an
        existing file) pass `create=False` to avoid a filesystem write on
        every call.
    """
    path = _candidate_path(settings)
    _reject_unsafe(path, settings)
    if create:
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(_CONFIG_DIR_MODE)
    return path

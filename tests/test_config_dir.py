import stat
import sys
from pathlib import Path

import pytest

from sbobina.config_dir import ConfigDirUnsafeError, resolve_config_dir
from sbobina.settings import Settings


def test_resolve_config_dir_defaults_to_dot_config_on_linux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    resolved = resolve_config_dir(settings=Settings())

    assert resolved == tmp_path / ".config" / "sbobina"


def test_resolve_config_dir_honors_xdg_config_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    resolved = resolve_config_dir(settings=Settings())

    assert resolved == xdg / "sbobina"


def test_resolve_config_dir_uses_appdata_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    appdata = tmp_path / "AppData" / "Roaming"
    monkeypatch.setenv("APPDATA", str(appdata))

    resolved = resolve_config_dir(settings=Settings())

    assert resolved == appdata / "sbobina"


def test_resolve_config_dir_uses_application_support_on_macos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))

    resolved = resolve_config_dir(settings=Settings())

    assert resolved == tmp_path / "Library" / "Application Support" / "sbobina"


def test_resolve_config_dir_explicit_override_wins(tmp_path: Path) -> None:
    override = tmp_path / "wherever"

    resolved = resolve_config_dir(settings=Settings(config_dir=override))

    assert resolved == override


def test_resolve_config_dir_creates_directory_with_0700(tmp_path: Path) -> None:
    override = tmp_path / "cfg"

    resolved = resolve_config_dir(settings=Settings(config_dir=override))

    mode = stat.S_IMODE(resolved.stat().st_mode)
    assert mode == 0o700


def test_resolve_config_dir_with_create_false_does_not_create_it(
    tmp_path: Path,
) -> None:
    override = tmp_path / "cfg"

    resolved = resolve_config_dir(settings=Settings(config_dir=override), create=False)

    assert resolved == override
    assert not override.exists()


def test_resolve_config_dir_rejects_a_path_under_data_dir(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    config_dir = data_dir / "x"

    with pytest.raises(ConfigDirUnsafeError):
        resolve_config_dir(settings=Settings(data_dir=data_dir, config_dir=config_dir))


def test_resolve_config_dir_rejects_the_repository_root(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    config_dir = repo_root / "whatever-not-created"

    with pytest.raises(ConfigDirUnsafeError):
        resolve_config_dir(settings=Settings(config_dir=config_dir), create=False)


def test_resolve_config_dir_allows_a_path_outside_both(tmp_path: Path) -> None:
    config_dir = tmp_path / "safe"

    resolved = resolve_config_dir(settings=Settings(config_dir=config_dir))

    assert resolved == config_dir

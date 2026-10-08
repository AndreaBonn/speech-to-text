import ctypes
import logging
import os
from contextlib import AbstractContextManager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from sbobina import cuda_libs


@pytest.fixture
def wheel_dirs(tmp_path: Path) -> tuple[Path, Path]:
    cublas_dir = tmp_path / "nvidia" / "cublas" / "lib"
    cudnn_dir = tmp_path / "nvidia" / "cudnn" / "lib"
    cublas_dir.mkdir(parents=True)
    cudnn_dir.mkdir(parents=True)
    return cublas_dir, cudnn_dir


def _fake_package(name: str, path: Path | None = None) -> ModuleType:
    module = ModuleType(name)
    module.__path__ = [str(path)] if path is not None else []
    return module


def _patch_wheels(
    cublas_dir: Path, cudnn_dir: Path
) -> AbstractContextManager[dict[str, ModuleType]]:
    nvidia = _fake_package("nvidia")
    nvidia_cublas = _fake_package("nvidia.cublas")
    nvidia_cudnn = _fake_package("nvidia.cudnn")
    cublas_lib = _fake_package("nvidia.cublas.lib", cublas_dir)
    cudnn_lib = _fake_package("nvidia.cudnn.lib", cudnn_dir)
    nvidia.__dict__.update(cublas=nvidia_cublas, cudnn=nvidia_cudnn)
    nvidia_cublas.__dict__.update(lib=cublas_lib)
    nvidia_cudnn.__dict__.update(lib=cudnn_lib)
    return patch.dict(
        "sys.modules",
        {
            "nvidia": nvidia,
            "nvidia.cublas": nvidia_cublas,
            "nvidia.cudnn": nvidia_cudnn,
            "nvidia.cublas.lib": cublas_lib,
            "nvidia.cudnn.lib": cudnn_lib,
        },
    )


def test_preload_missing_wheels_warns_and_returns_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        patch.dict("sys.modules", {"nvidia.cublas.lib": None}),
        caplog.at_level(logging.WARNING),
    ):
        loaded = cuda_libs.preload_cuda_libraries()
    assert loaded == []
    assert "GPU inference unavailable" in caplog.text


def test_preload_linux_loads_matching_shared_objects(
    wheel_dirs: tuple[Path, Path],
) -> None:
    cublas_dir, cudnn_dir = wheel_dirs
    (cublas_dir / "libcublas.so.12").touch()
    (cublas_dir / "libcublasLt.so.12").touch()
    (cudnn_dir / "libcudnn_ops.so.9").touch()
    (cudnn_dir / "ignored.so").touch()

    with (
        _patch_wheels(cublas_dir, cudnn_dir),
        patch.object(cuda_libs, "sys", SimpleNamespace(platform="linux")),
        patch.object(ctypes, "CDLL") as cdll,
    ):
        loaded = cuda_libs.preload_cuda_libraries()

    assert cdll.call_count == 3
    assert {path.name for path in loaded} == {
        "libcublas.so.12",
        "libcublasLt.so.12",
        "libcudnn_ops.so.9",
    }


def test_preload_windows_registers_bin_and_lib_directories(
    wheel_dirs: tuple[Path, Path],
) -> None:
    # cublas ships both bin/ (DLLs) and lib/ (the imported package dir);
    # cudnn only ships lib/, as on Linux: both must still be registered.
    cublas_dir, cudnn_dir = wheel_dirs
    (cublas_dir.parent / "bin").mkdir()
    with (
        _patch_wheels(cublas_dir, cudnn_dir),
        patch.object(cuda_libs, "sys", SimpleNamespace(platform="win32")),
        patch.object(os, "add_dll_directory", create=True) as add_dir,
    ):
        registered = cuda_libs.preload_cuda_libraries()

    assert add_dir.call_count == 3
    add_dir.assert_any_call(str(cublas_dir.parent / "bin"))
    add_dir.assert_any_call(str(cublas_dir))
    add_dir.assert_any_call(str(cudnn_dir))
    assert registered == [cublas_dir.parent / "bin", cublas_dir, cudnn_dir]


def test_preload_windows_no_directories_found_warns(
    wheel_dirs: tuple[Path, Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    cublas_dir, cudnn_dir = wheel_dirs
    cublas_dir.rmdir()
    cudnn_dir.rmdir()
    with (
        _patch_wheels(cublas_dir, cudnn_dir),
        patch.object(cuda_libs, "sys", SimpleNamespace(platform="win32")),
        patch.object(os, "add_dll_directory", create=True) as add_dir,
        caplog.at_level(logging.WARNING),
    ):
        registered = cuda_libs.preload_cuda_libraries()

    assert registered == []
    add_dir.assert_not_called()
    assert "Nessuna cartella DLL" in caplog.text


def test_register_windows_dll_directories_non_windows_registers_nothing(
    wheel_dirs: tuple[Path, Path],
) -> None:
    directories = list(wheel_dirs)
    with (
        patch.object(cuda_libs, "sys", SimpleNamespace(platform="linux")),
        patch.object(os, "add_dll_directory", create=True) as add_dir,
    ):
        non_windows = cuda_libs._register_windows_dll_directories(lib_dirs=directories)
        assert add_dir.call_args_list == []
        with patch.object(cuda_libs, "sys", SimpleNamespace(platform="win32")):
            windows = cuda_libs._register_windows_dll_directories(lib_dirs=directories)
        assert [call.args for call in add_dir.call_args_list] == [
            (str(path),) for path in directories
        ]

    assert non_windows == []
    assert windows == directories

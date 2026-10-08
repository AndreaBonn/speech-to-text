import ctypes
import logging
import os
from contextlib import AbstractContextManager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from sbobina import cuda_libs


def _make_wheel_dirs(root: Path, subdir: str) -> tuple[Path, Path]:
    cublas_dir = root / "nvidia" / "cublas" / subdir
    cudnn_dir = root / "nvidia" / "cudnn" / subdir
    cublas_dir.mkdir(parents=True)
    cudnn_dir.mkdir(parents=True)
    return cublas_dir, cudnn_dir


@pytest.fixture
def wheel_dirs(tmp_path: Path) -> tuple[Path, Path]:
    return _make_wheel_dirs(root=tmp_path, subdir="lib")


@pytest.fixture
def windows_wheel_dirs(tmp_path: Path) -> tuple[Path, Path]:
    # Layout of the win_amd64 wheels: DLLs under bin/, no lib/ directory.
    return _make_wheel_dirs(root=tmp_path, subdir="bin")


def _fake_package(name: str, path: Path | None = None) -> ModuleType:
    module = ModuleType(name)
    module.__path__ = [str(path)] if path is not None else []
    return module


def _patch_wheels(
    cublas_dir: Path, cudnn_dir: Path
) -> AbstractContextManager[dict[str, ModuleType]]:
    subdir = cublas_dir.name
    nvidia = _fake_package("nvidia")
    nvidia_cublas = _fake_package("nvidia.cublas")
    nvidia_cudnn = _fake_package("nvidia.cudnn")
    cublas_sub = _fake_package(f"nvidia.cublas.{subdir}", cublas_dir)
    cudnn_sub = _fake_package(f"nvidia.cudnn.{subdir}", cudnn_dir)
    nvidia.__dict__.update(cublas=nvidia_cublas, cudnn=nvidia_cudnn)
    nvidia_cublas.__dict__.update({subdir: cublas_sub})
    nvidia_cudnn.__dict__.update({subdir: cudnn_sub})
    return patch.dict(
        "sys.modules",
        {
            "nvidia": nvidia,
            "nvidia.cublas": nvidia_cublas,
            "nvidia.cudnn": nvidia_cudnn,
            f"nvidia.cublas.{subdir}": cublas_sub,
            f"nvidia.cudnn.{subdir}": cudnn_sub,
        },
    )


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("linux", ("nvidia.cublas.lib", "nvidia.cudnn.lib")),
        ("win32", ("nvidia.cublas.bin", "nvidia.cudnn.bin")),
    ],
)
def test_wheel_library_modules_follows_wheel_layout(
    platform: str, expected: tuple[str, str]
) -> None:
    assert cuda_libs.wheel_library_modules(platform=platform) == expected


def test_preload_missing_wheels_warns_and_returns_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        patch.dict("sys.modules", {"nvidia.cublas.lib": None}),
        patch.object(cuda_libs, "sys", SimpleNamespace(platform="linux")),
        caplog.at_level(logging.WARNING),
    ):
        loaded = cuda_libs.preload_cuda_libraries()
    assert loaded == []
    assert "GPU inference unavailable" in caplog.text


def test_preload_windows_with_linux_layout_warns_and_returns_empty(
    wheel_dirs: tuple[Path, Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Only lib/ present: on Windows that is not where the DLLs live.
    cublas_dir, cudnn_dir = wheel_dirs
    with (
        _patch_wheels(cublas_dir, cudnn_dir),
        patch.dict("sys.modules", {"nvidia.cublas.bin": None}),
        patch.object(cuda_libs, "sys", SimpleNamespace(platform="win32")),
        patch.object(os, "add_dll_directory", create=True) as add_dir,
        caplog.at_level(logging.WARNING),
    ):
        loaded = cuda_libs.preload_cuda_libraries()
    assert loaded == []
    add_dir.assert_not_called()
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


def test_preload_windows_registers_bin_and_loads_cuda_dlls(
    windows_wheel_dirs: tuple[Path, Path],
) -> None:
    cublas_dir, cudnn_dir = windows_wheel_dirs
    for name in ("cublas64_12.dll", "cublasLt64_12.dll", "nvblas64_12.dll"):
        (cublas_dir / name).touch()
    for name in ("cudnn64_9.dll", "cudnn_ops64_9.dll"):
        (cudnn_dir / name).touch()

    with (
        _patch_wheels(cublas_dir, cudnn_dir),
        patch.object(cuda_libs, "sys", SimpleNamespace(platform="win32")),
        patch.object(os, "add_dll_directory", create=True) as add_dir,
        patch.object(ctypes, "CDLL") as cdll,
    ):
        loaded = cuda_libs.preload_cuda_libraries()

    assert [call.args for call in add_dir.call_args_list] == [
        (str(cublas_dir),),
        (str(cudnn_dir),),
    ]
    # cublasLt first: cublas64_12.dll depends on it; nvblas is never needed.
    assert [path.name for path in loaded] == [
        "cublasLt64_12.dll",
        "cublas64_12.dll",
        "cudnn64_9.dll",
        "cudnn_ops64_9.dll",
    ]
    assert [call.args for call in cdll.call_args_list] == [
        (str(path),) for path in loaded
    ]


def test_preload_windows_dll_load_failure_propagates(
    windows_wheel_dirs: tuple[Path, Path],
) -> None:
    # transcriber._preload_cuda_if_needed turns OSError into a CPU fallback.
    cublas_dir, cudnn_dir = windows_wheel_dirs
    (cublas_dir / "cublas64_12.dll").touch()
    with (
        _patch_wheels(cublas_dir, cudnn_dir),
        patch.object(cuda_libs, "sys", SimpleNamespace(platform="win32")),
        patch.object(os, "add_dll_directory", create=True),
        patch.object(ctypes, "CDLL", side_effect=OSError("missing dependency")),
        pytest.raises(OSError, match="missing dependency"),
    ):
        cuda_libs.preload_cuda_libraries()


def test_register_windows_dll_directories_non_windows_registers_nothing(
    windows_wheel_dirs: tuple[Path, Path],
) -> None:
    directories = list(windows_wheel_dirs)
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

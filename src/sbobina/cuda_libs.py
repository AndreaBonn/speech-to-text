import ctypes
import importlib
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# ctranslate2 dlopen()s cuBLAS/cuDNN by soname; the pip wheels live outside the
# loader search path, so we load them globally before faster_whisper is imported.
_LIB_GLOBS = ("libcublasLt.so.12", "libcublas.so.12", "libcudnn*.so.9")
# Windows equivalent, cublasLt first since cublas64_12.dll imports it. Loading
# by full path also makes later LoadLibrary calls by bare name (cuDNN loads its
# sub-libraries that way) resolve to the already loaded module.
_DLL_GLOBS = ("cublasLt64_12.dll", "cublas64_12.dll", "cudnn*64_9.dll")


def wheel_library_modules(platform: str) -> tuple[str, str]:
    """Import names of the wheel directories holding cuBLAS and cuDNN.

    The Linux wheels put the shared objects under ``lib/``; the win_amd64
    wheels have no ``lib/`` and ship the DLLs under ``bin/`` (measured on
    nvidia-cublas-cu12 12.9.2.10 and nvidia-cudnn-cu12 9.27.0.42).
    """
    subdir = "bin" if platform == "win32" else "lib"
    return f"nvidia.cublas.{subdir}", f"nvidia.cudnn.{subdir}"


def _wheel_library_dirs() -> list[Path] | None:
    try:
        modules = [
            importlib.import_module(name)
            for name in wheel_library_modules(platform=sys.platform)
        ]
    except ImportError:
        return None
    return [Path(next(iter(module.__path__))) for module in modules]


def _load_matching(lib_dirs: list[Path], patterns: tuple[str, ...]) -> list[Path]:
    loaded: list[Path] = []
    for pattern in patterns:
        for lib_dir in lib_dirs:
            for lib_path in sorted(lib_dir.glob(pattern)):
                if sys.platform == "win32":
                    ctypes.CDLL(str(lib_path))
                else:
                    ctypes.CDLL(str(lib_path), mode=ctypes.RTLD_GLOBAL)
                loaded.append(lib_path)
    return loaded


def _register_windows_dll_directories(lib_dirs: list[Path]) -> list[Path]:
    # Explicit platform check: os.add_dll_directory exists only on Windows.
    if sys.platform != "win32":
        return []
    for lib_dir in lib_dirs:
        os.add_dll_directory(str(lib_dir))
        logger.info("Registrata cartella DLL CUDA: %s", lib_dir)
    return list(lib_dirs)


def preload_cuda_libraries() -> list[Path]:
    """Load the pip-installed NVIDIA libraries before ctranslate2 needs them.

    On Linux the shared objects are loaded into the global symbol namespace; on
    Windows their ``bin/`` directories are also added to the DLL search path.

    Returns
    -------
    list[Path]
        The libraries loaded; empty when the wheels are absent (CPU-only
        install), in which case CUDA inference will fail loudly later.

    Raises
    ------
    OSError
        A library exists but cannot be loaded (missing system dependency).
    """
    lib_dirs = _wheel_library_dirs()
    if lib_dirs is None:
        logger.warning("NVIDIA pip wheels not found: GPU inference unavailable")
        return []
    if sys.platform == "win32":
        _register_windows_dll_directories(lib_dirs=lib_dirs)
        return _load_matching(lib_dirs=lib_dirs, patterns=_DLL_GLOBS)
    return _load_matching(lib_dirs=lib_dirs, patterns=_LIB_GLOBS)

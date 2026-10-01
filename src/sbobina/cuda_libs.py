import ctypes
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# ctranslate2 dlopen()s cuBLAS/cuDNN by soname; the pip wheels live outside the
# loader search path, so we load them globally before faster_whisper is imported.
_LIB_GLOBS = ("libcublasLt.so.12", "libcublas.so.12", "libcudnn*.so.9")
# Windows wheels ship the DLLs under one of these subdirectories of the
# ``nvidia.cublas``/``nvidia.cudnn`` package (BASIS: inferred, layout not
# observable on this machine).
_DLL_SUBDIRS = ("bin", "lib")


def _wheel_package_dirs() -> list[Path] | None:
    try:
        import nvidia.cublas.lib as cublas_lib
        import nvidia.cudnn.lib as cudnn_lib
    except ImportError:
        return None
    return [Path(next(iter(mod.__path__))) for mod in (cublas_lib, cudnn_lib)]


def _preload_linux(lib_dirs: list[Path]) -> list[Path]:
    loaded: list[Path] = []
    for pattern in _LIB_GLOBS:
        for lib_dir in lib_dirs:
            for lib_path in sorted(lib_dir.glob(pattern)):
                ctypes.CDLL(str(lib_path), mode=ctypes.RTLD_GLOBAL)
                loaded.append(lib_path)
    return loaded


def _register_windows_dll_directories(lib_dirs: list[Path]) -> list[Path]:
    # Explicit platform check: os.add_dll_directory exists only on Windows.
    if sys.platform != "win32":
        return []
    registered: list[Path] = []
    for lib_dir in lib_dirs:
        package_dir = lib_dir.parent
        for subdir in _DLL_SUBDIRS:
            candidate = package_dir / subdir
            if candidate.is_dir():
                os.add_dll_directory(str(candidate))
                registered.append(candidate)
                logger.info("Registrata cartella DLL CUDA: %s", candidate)
    if not registered:
        logger.warning("Nessuna cartella DLL NVIDIA trovata sotto %s", lib_dirs)
    return registered


def preload_cuda_libraries() -> list[Path]:
    """Make the pip-installed NVIDIA libraries loadable before ctranslate2 needs them.

    On Linux the shared objects are loaded into the global symbol namespace; on
    Windows the DLL search path is extended instead, since ``ctypes.CDLL`` is
    not how CTranslate2 locates DLLs there.

    Returns
    -------
    list[Path]
        The libraries loaded (Linux) or directories registered (Windows);
        empty when the wheels are absent (CPU-only install), in which case
        CUDA inference will fail loudly later.
    """
    lib_dirs = _wheel_package_dirs()
    if lib_dirs is None:
        logger.warning("NVIDIA pip wheels not found: GPU inference unavailable")
        return []
    if sys.platform == "win32":
        return _register_windows_dll_directories(lib_dirs)
    return _preload_linux(lib_dirs)

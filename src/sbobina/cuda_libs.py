import ctypes
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ctranslate2 dlopen()s cuBLAS/cuDNN by soname; the pip wheels live outside the
# loader search path, so we load them globally before faster_whisper is imported.
_LIB_GLOBS = ("libcublasLt.so.12", "libcublas.so.12", "libcudnn*.so.9")


def preload_cuda_libraries() -> list[Path]:
    """Load the pip-installed NVIDIA libraries into the global symbol namespace.

    Returns
    -------
    list[Path]
        The shared objects that were loaded; empty when the wheels are absent
        (CPU-only install), in which case CUDA inference will fail loudly later.
    """
    try:
        import nvidia.cublas.lib as cublas_lib
        import nvidia.cudnn.lib as cudnn_lib
    except ImportError:
        logger.warning("NVIDIA pip wheels not found: GPU inference unavailable")
        return []

    lib_dirs = [Path(next(iter(mod.__path__))) for mod in (cublas_lib, cudnn_lib)]
    loaded: list[Path] = []
    for pattern in _LIB_GLOBS:
        for lib_dir in lib_dirs:
            for lib_path in sorted(lib_dir.glob(pattern)):
                ctypes.CDLL(str(lib_path), mode=ctypes.RTLD_GLOBAL)
                loaded.append(lib_path)
    return loaded

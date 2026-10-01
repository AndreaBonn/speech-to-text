import importlib.util
import os
import platform
import sys
from dataclasses import dataclass
from typing import Literal

SystemName = Literal["linux", "windows", "darwin", "other"]
CUDA_LIBRARY_MODULES = ("nvidia.cublas.lib", "nvidia.cudnn.lib")


@dataclass(frozen=True)
class PlatformInfo:
    """What ``detect_platform`` found on this machine: OS, GPU and CPU support."""

    system: SystemName
    machine: str
    is_apple_silicon: bool
    cuda_devices: int
    cuda_libs_available: bool
    cpu_compute_types: frozenset[str]
    cpu_count: int


@dataclass(frozen=True)
class RuntimeRequest:
    """What the user asked for; ``"auto"`` fields are resolved by ``resolve_runtime``."""

    device: str
    compute_type: str
    whisper_model: str
    whisper_model_gpu: str
    whisper_model_cpu: str
    cpu_threads: int  # 0 = one per CPU core


@dataclass(frozen=True)
class RuntimeChoice:
    """Arguments for ``WhisperModel``; ``cpu_threads`` is None on CUDA."""

    device: str
    compute_type: str
    whisper_model: str
    cpu_threads: int | None
    reason: str


def detect_platform() -> PlatformInfo:
    """Probe capabilities without loading CUDA libraries or instantiating a model."""
    ctranslate2 = importlib.import_module("ctranslate2")

    systems: dict[str, SystemName] = {
        "linux": "linux",
        "win32": "windows",
        "darwin": "darwin",
    }
    system = systems.get(sys.platform, "other")
    machine = platform.machine()
    try:
        cuda_libs_available = all(
            importlib.util.find_spec(name) is not None for name in CUDA_LIBRARY_MODULES
        )
    except ModuleNotFoundError:
        # find_spec raises when an optional NVIDIA parent package is absent.
        cuda_libs_available = False
    return PlatformInfo(
        system=system,
        machine=machine,
        is_apple_silicon=system == "darwin" and machine in {"arm64", "aarch64"},
        cuda_devices=ctranslate2.get_cuda_device_count(),
        cuda_libs_available=cuda_libs_available,
        cpu_compute_types=frozenset(ctranslate2.get_supported_compute_types("cpu")),
        cpu_count=os.cpu_count() or 1,
    )


def _resolve_device(info: PlatformInfo, requested: RuntimeRequest) -> tuple[str, str]:
    if requested.device == "cuda" and info.cuda_devices == 0:
        raise ValueError("CUDA requested but no NVIDIA GPU is available")
    if requested.device != "auto":
        return requested.device, f"Device richiesto esplicitamente: {requested.device}"
    if info.system == "linux" and info.cuda_devices > 0:
        if info.cuda_libs_available:
            return "cuda", "GPU NVIDIA e wheel CUDA disponibili su Linux"
        return "cpu", "Wheel CUDA mancanti su Linux"
    if info.system == "windows":
        return "cpu", "Supporto DLL CUDA su Windows non ancora abilitato"
    if info.system == "darwin":
        return "cpu", "CTranslate2 su macOS usa la CPU"
    return "cpu", "Nessun percorso CUDA automatico disponibile"


def _resolve_compute_type(info: PlatformInfo, device: str, requested: str) -> str:
    if requested != "auto":
        return requested
    if device == "cuda":
        return "float16"
    return "int8" if "int8" in info.cpu_compute_types else "float32"


def resolve_runtime(info: PlatformInfo, requested: RuntimeRequest) -> RuntimeChoice:
    """Pick device, compute type and Whisper model for this machine.

    Parameters
    ----------
    info : PlatformInfo
        Capabilities found by ``detect_platform``.
    requested : RuntimeRequest
        User preferences; explicit values always win over ``"auto"``.

    Returns
    -------
    RuntimeChoice
        Arguments for ``WhisperModel`` plus the reason for the device choice.

    Raises
    ------
    ValueError
        CUDA requested explicitly but no NVIDIA GPU is visible.

    References
    ----------
    CTranslate2 runs on NVIDIA GPUs only (no Metal backend), and int8 on x86-64
    and ARM64 CPUs: https://opennmt.net/CTranslate2/hardware_support.html,
    https://opennmt.net/CTranslate2/quantization.html
    """
    device, reason = _resolve_device(info, requested=requested)
    model = requested.whisper_model
    if model == "auto":
        gpu = device == "cuda"
        model = requested.whisper_model_gpu if gpu else requested.whisper_model_cpu
    cpu_threads = requested.cpu_threads or info.cpu_count
    return RuntimeChoice(
        device=device,
        compute_type=_resolve_compute_type(
            info, device=device, requested=requested.compute_type
        ),
        whisper_model=model,
        cpu_threads=cpu_threads if device == "cpu" else None,
        reason=reason,
    )

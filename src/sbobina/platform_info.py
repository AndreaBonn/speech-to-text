import importlib.util
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sbobina.settings import Settings

SystemName = Literal["linux", "windows", "darwin", "other"]
CUDA_LIBRARY_MODULES = ("nvidia.cublas.lib", "nvidia.cudnn.lib")
CPUINFO_PATH = Path("/proc/cpuinfo")


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


def count_physical_cores(cpuinfo: str) -> int | None:
    """Count distinct (physical id, core id) pairs in ``/proc/cpuinfo`` text.

    Returns ``None`` when the file does not report core ids (some ARM boards).
    """
    cores: set[tuple[str, str]] = set()
    package = ""
    for line in cpuinfo.splitlines():
        key, _, value = line.partition(":")
        match key.strip():
            case "physical id":
                package = value.strip()
            case "core id":
                cores.add((package, value.strip()))
    return len(cores) or None


def _cpu_thread_count(system: SystemName) -> int:
    # One thread per physical core: on a 10-core/16-thread laptop, 5 min of
    # audio took 85.5 s with 10 threads and 102.1 s with 16 (3 runs each).
    # No stdlib API for physical cores elsewhere: logical count there.
    logical = os.cpu_count() or 1
    if system != "linux":
        return logical
    try:
        physical = count_physical_cores(CPUINFO_PATH.read_text(encoding="utf-8"))
    except OSError:
        return logical
    return physical or logical


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
        cpu_count=_cpu_thread_count(system),
    )


_CUDA_AUTO_SYSTEMS: frozenset[SystemName] = frozenset({"linux", "windows"})


def _resolve_device(info: PlatformInfo, requested: RuntimeRequest) -> tuple[str, str]:
    if requested.device == "cuda" and info.cuda_devices == 0:
        raise ValueError("CUDA requested but no NVIDIA GPU is available")
    if requested.device != "auto":
        return requested.device, f"Device richiesto esplicitamente: {requested.device}"
    if info.system in _CUDA_AUTO_SYSTEMS and info.cuda_devices > 0:
        if info.cuda_libs_available:
            return "cuda", f"GPU NVIDIA e librerie CUDA disponibili su {info.system}"
        return "cpu", "GPU NVIDIA presente ma librerie CUDA non installate"
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


def request_from_settings(config: Settings) -> RuntimeRequest:
    """The runtime preferences carried by ``config`` (CLI, job or server)."""
    return RuntimeRequest(
        device=config.device,
        compute_type=config.compute_type,
        whisper_model=config.whisper_model,
        whisper_model_gpu=config.whisper_model_gpu,
        whisper_model_cpu=config.whisper_model_cpu,
        cpu_threads=config.cpu_threads,
    )


def resolve_for_settings(config: Settings) -> tuple[PlatformInfo, RuntimeChoice]:
    """Detect this machine and resolve ``config`` against it."""
    info = detect_platform()
    return info, resolve_runtime(info=info, requested=request_from_settings(config))

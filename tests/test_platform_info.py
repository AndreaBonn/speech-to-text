from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from sbobina import platform_info
from sbobina.platform_info import (
    PlatformInfo,
    RuntimeChoice,
    RuntimeRequest,
    SystemName,
    resolve_runtime,
)
from sbobina.settings import Settings


@pytest.fixture
def requested() -> RuntimeRequest:
    return RuntimeRequest(
        device="auto",
        compute_type="auto",
        whisper_model="auto",
        whisper_model_gpu="large-v3",
        whisper_model_cpu="large-v3-turbo",
        cpu_threads=0,
    )


@pytest.fixture
def linux_gpu() -> PlatformInfo:
    return PlatformInfo(
        system="linux",
        machine="x86_64",
        is_apple_silicon=False,
        cuda_devices=1,
        cuda_libs_available=True,
        cpu_compute_types=frozenset({"int8", "float32"}),
        cpu_count=8,
    )


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        (("linux", "x86_64", False, 1, True), ("cuda", "float16", "large-v3", None)),
        (("linux", "x86_64", False, 1, False), ("cpu", "int8", "large-v3-turbo", 8)),
        (("linux", "x86_64", False, 0, False), ("cpu", "int8", "large-v3-turbo", 8)),
        (("windows", "AMD64", False, 1, True), ("cuda", "float16", "large-v3", None)),
        (("windows", "AMD64", False, 1, False), ("cpu", "int8", "large-v3-turbo", 8)),
        (("windows", "AMD64", False, 0, False), ("cpu", "int8", "large-v3-turbo", 8)),
        (("darwin", "x86_64", False, 1, True), ("cpu", "int8", "large-v3-turbo", 8)),
        (("darwin", "x86_64", False, 1, False), ("cpu", "int8", "large-v3-turbo", 8)),
        (("darwin", "x86_64", False, 0, False), ("cpu", "int8", "large-v3-turbo", 8)),
        (("darwin", "arm64", True, 1, True), ("cpu", "int8", "large-v3-turbo", 8)),
        (("darwin", "arm64", True, 1, False), ("cpu", "int8", "large-v3-turbo", 8)),
        (("darwin", "arm64", True, 0, False), ("cpu", "int8", "large-v3-turbo", 8)),
        (("other", "aarch64", False, 1, True), ("cpu", "int8", "large-v3-turbo", 8)),
        (("other", "aarch64", False, 1, False), ("cpu", "int8", "large-v3-turbo", 8)),
        (("other", "aarch64", False, 0, False), ("cpu", "int8", "large-v3-turbo", 8)),
    ],
)
def test_resolve_runtime_auto_platform_selects_expected_configuration(
    scenario: tuple[SystemName, str, bool, int, bool],
    expected: tuple[str, str, str, int | None],
    requested: RuntimeRequest,
) -> None:
    system, machine, apple_silicon, devices, libraries = scenario
    info = PlatformInfo(
        system=system,
        machine=machine,
        is_apple_silicon=apple_silicon,
        cuda_devices=devices,
        cuda_libs_available=libraries,
        cpu_compute_types=frozenset({"int8", "float32"}),
        cpu_count=8,
    )

    choice = resolve_runtime(info=info, requested=requested)

    assert (
        choice.device,
        choice.compute_type,
        choice.whisper_model,
        choice.cpu_threads,
    ) == expected
    assert choice.reason


def test_resolve_runtime_cpu_without_int8_uses_float32(
    linux_gpu: PlatformInfo,
    requested: RuntimeRequest,
) -> None:
    info = replace(linux_gpu, cuda_devices=0, cpu_compute_types=frozenset({"float32"}))
    choice = resolve_runtime(info, requested=requested)
    assert (choice.device, choice.compute_type) == ("cpu", "float32")


def test_resolve_runtime_explicit_cuda_without_gpu_raises(
    linux_gpu: PlatformInfo,
    requested: RuntimeRequest,
) -> None:
    with pytest.raises(ValueError, match="CUDA.*no.*GPU"):
        resolve_runtime(
            replace(linux_gpu, cuda_devices=0),
            requested=replace(requested, device="cuda"),
        )


def test_resolve_runtime_explicit_cpu_preserves_overrides(
    linux_gpu: PlatformInfo,
    requested: RuntimeRequest,
) -> None:
    choice = resolve_runtime(
        linux_gpu,
        requested=replace(
            requested,
            device="cpu",
            compute_type="float32",
            cpu_threads=3,
            whisper_model="small",
        ),
    )
    assert choice == RuntimeChoice(
        device="cpu",
        compute_type="float32",
        whisper_model="small",
        cpu_threads=3,
        reason="Device richiesto esplicitamente: cpu",
    )


def test_resolve_runtime_explicit_default_model_stays_on_cpu(
    linux_gpu: PlatformInfo,
    requested: RuntimeRequest,
) -> None:
    choice = resolve_runtime(
        linux_gpu,
        requested=replace(
            requested,
            device="cpu",
            whisper_model="large-v3",
        ),
    )
    assert (choice.device, choice.whisper_model) == ("cpu", "large-v3")


@pytest.mark.parametrize("system", ["linux", "windows", "darwin", "other"])
def test_resolve_runtime_explicit_cuda_wins_without_wheels(
    system: SystemName,
    linux_gpu: PlatformInfo,
    requested: RuntimeRequest,
) -> None:
    choice = resolve_runtime(
        replace(linux_gpu, system=system, cuda_libs_available=False),
        requested=replace(requested, device="cuda", compute_type="int8_float16"),
    )
    assert (choice.device, choice.compute_type, choice.cpu_threads) == (
        "cuda",
        "int8_float16",
        None,
    )


def test_settings_default_runtime_uses_auto_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for field in Settings.model_fields:
        monkeypatch.delenv(f"SBOBINA_{field.upper()}", raising=False)

    config = Settings()

    assert (
        config.device,
        config.compute_type,
        config.cpu_threads,
        config.whisper_model,
        config.whisper_model_gpu,
        config.whisper_model_cpu,
    ) == ("auto", "auto", 0, "auto", "large-v3", "large-v3-turbo")


def test_settings_positive_cpu_threads_preserves_override() -> None:
    config = Settings(cpu_threads=3)

    assert config.cpu_threads == 3


def test_settings_negative_cpu_threads_raises_validation_error() -> None:
    with pytest.raises(ValidationError, match="cpu_threads"):
        Settings(cpu_threads=-1)


@pytest.mark.parametrize(
    ("field", "value"),
    [("device", "gpu"), ("device", "CUDA"), ("compute_type", "fp16")],
)
def test_settings_unknown_runtime_value_raises(field: str, value: str) -> None:
    with pytest.raises(ValidationError, match=field):
        Settings.model_validate({field: value})


@pytest.mark.parametrize(
    "scenario,expected_system",
    [
        (("linux", "x86_64", 1, True, 8), "linux"),
        (("win32", "AMD64", 0, False, 4), "windows"),
        (("darwin", "arm64", 0, False, 8), "darwin"),
        (("darwin", "aarch64", 0, False, 8), "darwin"),
        (("darwin", "x86_64", 0, False, 8), "darwin"),
        (("freebsd", "aarch64", 0, False, None), "other"),
    ],
)
def test_detect_platform_reports_mocked_capabilities(
    monkeypatch: pytest.MonkeyPatch,
    scenario: tuple[str, str, int, bool, int | None],
    expected_system: SystemName,
) -> None:
    system, machine, devices, wheels, cores = scenario
    monkeypatch.setattr(platform_info, "sys", SimpleNamespace(platform=system))
    monkeypatch.setattr("platform.machine", lambda: machine)
    monkeypatch.setattr("os.cpu_count", lambda: cores)
    monkeypatch.setattr(platform_info, "CPUINFO_PATH", Path("/nonexistent/cpuinfo"))
    monkeypatch.setattr("ctranslate2.get_cuda_device_count", lambda: devices)
    monkeypatch.setattr(
        "ctranslate2.get_supported_compute_types", lambda device: {"int8", "float32"}
    )
    with patch(
        "importlib.util.find_spec", return_value=object() if wheels else None
    ) as find_spec:
        info = platform_info.detect_platform()
    assert info == PlatformInfo(
        system=expected_system,
        machine=machine,
        is_apple_silicon=system == "darwin" and machine in {"arm64", "aarch64"},
        cuda_devices=devices,
        cuda_libs_available=wheels,
        cpu_compute_types=frozenset({"int8", "float32"}),
        cpu_count=cores or 1,
    )
    if wheels:
        assert find_spec.call_count == 2
        find_spec.assert_any_call("nvidia.cublas.lib")
        find_spec.assert_any_call("nvidia.cudnn.lib")


@pytest.mark.parametrize(
    "specs",
    [
        [ModuleNotFoundError("No module named 'nvidia'")],
        [object(), None],
        [None],
    ],
)
def test_detect_platform_missing_wheel_is_unavailable(specs: list[object]) -> None:
    with (
        patch.object(platform_info, "sys", SimpleNamespace(platform="linux")),
        patch("platform.machine", return_value="x86_64"),
        patch("os.cpu_count", return_value=4),
        patch.object(platform_info, "CPUINFO_PATH", Path("/nonexistent/cpuinfo")),
        patch("ctranslate2.get_cuda_device_count", return_value=1),
        patch("ctranslate2.get_supported_compute_types", return_value={"float32"}),
        patch("importlib.util.find_spec", side_effect=specs),
    ):
        info = platform_info.detect_platform()
    assert info == PlatformInfo(
        system="linux",
        machine="x86_64",
        is_apple_silicon=False,
        cuda_devices=1,
        cuda_libs_available=False,
        cpu_compute_types=frozenset({"float32"}),
        cpu_count=4,
    )


def test_request_from_settings_copies_runtime_preferences() -> None:
    config = Settings(
        device="cpu", compute_type="int8", whisper_model="small", cpu_threads=4
    )

    request = platform_info.request_from_settings(config=config)

    assert request == RuntimeRequest(
        device="cpu",
        compute_type="int8",
        whisper_model="small",
        whisper_model_gpu=config.whisper_model_gpu,
        whisper_model_cpu=config.whisper_model_cpu,
        cpu_threads=4,
    )


def _cpuinfo(cores: list[tuple[int, int]]) -> str:
    blocks = [
        f"processor\t: {index}\nphysical id\t: {package}\ncore id\t\t: {core}\n"
        for index, (package, core) in enumerate(cores)
    ]
    return "\n".join(blocks)


def test_count_physical_cores_collapses_hyperthreads() -> None:
    # Hybrid laptop: 6 cores with two threads each plus 4 single-thread cores.
    cores = [(0, c) for c in range(6) for _ in range(2)] + [
        (0, c) for c in range(8, 12)
    ]
    assert platform_info.count_physical_cores(_cpuinfo(cores)) == 10


def test_count_physical_cores_counts_cores_per_package() -> None:
    cores = [(package, core) for package in (0, 1) for core in range(4)]
    assert platform_info.count_physical_cores(_cpuinfo(cores)) == 8


def test_count_physical_cores_without_core_ids_is_unknown() -> None:
    assert (
        platform_info.count_physical_cores("processor\t: 0\nmodel name\t: ARM\n")
        is None
    )


def test_detect_platform_linux_uses_physical_cores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cpuinfo = tmp_path / "cpuinfo"
    cpuinfo.write_text(_cpuinfo([(0, c) for c in range(4) for _ in range(2)]))
    monkeypatch.setattr(platform_info, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(platform_info, "CPUINFO_PATH", cpuinfo)
    monkeypatch.setattr("os.cpu_count", lambda: 8)

    assert platform_info.detect_platform().cpu_count == 4


def test_detect_platform_linux_without_core_ids_uses_logical_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cpuinfo = tmp_path / "cpuinfo"
    cpuinfo.write_text("processor\t: 0\nmodel name\t: ARM\n")
    monkeypatch.setattr(platform_info, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(platform_info, "CPUINFO_PATH", cpuinfo)
    monkeypatch.setattr("os.cpu_count", lambda: 6)

    assert platform_info.detect_platform().cpu_count == 6

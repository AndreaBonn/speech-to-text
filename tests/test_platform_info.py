from dataclasses import replace
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
    "system,machine",
    [
        ("linux", "x86_64"),
        ("windows", "AMD64"),
        ("darwin", "x86_64"),
        ("darwin", "arm64"),
        ("other", "aarch64"),
    ],
)
@pytest.mark.parametrize("hardware", [(1, True), (1, False), (0, False)])
def test_resolve_runtime_auto_platform_matrix(
    system: SystemName,
    machine: str,
    hardware: tuple[int, bool],
    requested: RuntimeRequest,
) -> None:
    info = PlatformInfo(
        system=system,
        machine=machine,
        is_apple_silicon=system == "darwin" and machine == "arm64",
        cuda_devices=hardware[0],
        cuda_libs_available=hardware[1],
        cpu_compute_types=frozenset({"int8", "float32"}),
        cpu_count=8,
    )
    choice = resolve_runtime(info, requested=requested)
    uses_cuda = system in ("linux", "windows") and hardware == (1, True)
    assert (
        choice.device,
        choice.compute_type,
        choice.whisper_model,
        choice.cpu_threads,
    ) == (
        ("cuda", "float16", "large-v3", None)
        if uses_cuda
        else ("cpu", "int8", "large-v3-turbo", 8)
    )
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


def test_settings_runtime_defaults_and_thread_validation(
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
    assert Settings(cpu_threads=3).cpu_threads == 3
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

import logging
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import faster_whisper
import numpy as np
import pytest

from sbobina import platform_info, transcriber
from sbobina.models import Word
from sbobina.notices import USER_NOTICE
from sbobina.platform_info import PlatformInfo, SystemName
from sbobina.settings import Settings
from sbobina.transcriber import to_segment


@pytest.fixture
def cpu_platform() -> PlatformInfo:
    return PlatformInfo(
        system="linux",
        machine="x86_64",
        is_apple_silicon=False,
        cuda_devices=0,
        cuda_libs_available=False,
        cpu_compute_types=frozenset({"int8", "float32"}),
        cpu_count=8,
    )


@pytest.fixture(autouse=True)
def isolate_runtime(
    monkeypatch: pytest.MonkeyPatch, cpu_platform: PlatformInfo
) -> None:
    monkeypatch.setattr(platform_info, "detect_platform", lambda: cpu_platform)
    monkeypatch.setattr(transcriber, "preload_cuda_libraries", list)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for field in Settings.model_fields:
        monkeypatch.delenv(f"SBOBINA_{field.upper()}", raising=False)


def test_to_segment_converts_numpy_floats_and_keeps_word_text() -> None:
    raw = SimpleNamespace(
        start=np.float64(1.0),
        end=np.float64(2.0),
        words=[
            SimpleNamespace(
                start=1.0, end=1.5, word=" Noether", probability=np.float64(0.67)
            )
        ],
    )

    segment = to_segment(raw)

    assert segment is not None
    assert segment.words == (
        Word(start=1.0, end=1.5, text=" Noether", probability=0.67),
    )
    assert type(segment.words[0].probability) is float


def test_to_segment_without_words_returns_none() -> None:
    raw = SimpleNamespace(start=0.0, end=1.0, words=None)

    assert to_segment(raw) is None


def test_transcribe_file_passes_vad_setting_to_whisper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    class FakeWhisperModel:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def transcribe(
            self, audio: str, **kwargs: object
        ) -> tuple[list[object], object]:
            captured.update(kwargs)
            return [], SimpleNamespace(duration=0.0)

    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeWhisperModel)

    transcriber.transcribe_file(tmp_path / "a.m4a", config=Settings(vad_filter=False))

    assert captured["vad_filter"] is False
    assert captured["word_timestamps"] is True


@pytest.mark.parametrize("track_progress", [True, False])
def test_transcribe_file_empty_segment_advances_progress(
    tmp_path: Path, track_progress: bool
) -> None:
    calls: list[tuple[float, float]] = []
    raw_segments = [
        SimpleNamespace(start=0.0, end=10.0, words=None),
        SimpleNamespace(
            start=10.0,
            end=30.0,
            words=[
                SimpleNamespace(start=10.0, end=30.0, word=" ciao", probability=0.9)
            ],
        ),
    ]
    with patch("faster_whisper.WhisperModel") as model:
        model.return_value.transcribe.return_value = (
            raw_segments,
            SimpleNamespace(duration=30.0),
        )
        if track_progress:
            result = transcriber.transcribe_file(
                tmp_path / "a.m4a",
                config=Settings(),
                on_progress=lambda end, duration: calls.append((end, duration)),
            )
        else:
            result = transcriber.transcribe_file(tmp_path / "a.m4a", config=Settings())

    assert result.text == "ciao"
    assert calls == ([(10.0, 30.0), (30.0, 30.0)] if track_progress else [])


def test_collect_segments_default_callback_preserves_segments() -> None:
    raw = SimpleNamespace(
        start=0.0,
        end=10.0,
        words=[SimpleNamespace(start=0.0, end=10.0, word=" ciao", probability=0.9)],
    )

    segments = transcriber._collect_segments([raw], duration=10.0)

    assert len(segments) == 1
    assert segments[0].text == "ciao"


@pytest.mark.parametrize("threads,expected_threads", [(0, 8), (3, 3)])
def test_transcribe_file_cpu_arguments_and_runtime_log(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    threads: int,
    expected_threads: int,
) -> None:
    with (
        patch("faster_whisper.WhisperModel") as model,
        patch.object(transcriber, "preload_cuda_libraries") as preload,
        caplog.at_level(logging.INFO),
    ):
        model.return_value.transcribe.return_value = ([], SimpleNamespace(duration=0.0))
        result = transcriber.transcribe_file(
            tmp_path / "a.m4a", config=Settings(cpu_threads=threads)
        )
    model.assert_called_once_with(
        "large-v3-turbo",
        device="cpu",
        compute_type="int8",
        cpu_threads=expected_threads,
    )
    assert (preload.call_count, result.model) == (0, "large-v3-turbo")
    for value in (
        "linux",
        "cpu",
        "int8",
        "large-v3-turbo",
        "Nessun percorso CUDA automatico disponibile",
    ):
        assert value in caplog.text


@pytest.mark.parametrize("system", ["linux", "windows"])
def test_transcribe_file_cuda_preloads_on_linux_and_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cpu_platform: PlatformInfo,
    system: SystemName,
) -> None:
    info = replace(
        cpu_platform, system=system, cuda_devices=1, cuda_libs_available=True
    )
    monkeypatch.setattr(platform_info, "detect_platform", lambda: info)
    with (
        patch("faster_whisper.WhisperModel") as model,
        patch.object(transcriber, "preload_cuda_libraries") as preload,
    ):
        model.return_value.transcribe.return_value = ([], SimpleNamespace(duration=0.0))
        result = transcriber.transcribe_file(
            tmp_path / "a.m4a", config=Settings(device="cuda", cpu_threads=3)
        )
    model.assert_called_once_with("large-v3", device="cuda", compute_type="float16")
    assert preload.call_count == 1
    assert result.model == "large-v3"


@pytest.mark.parametrize(
    "whisper_model,expected_model", [("auto", "large-v3-turbo"), ("small", "small")]
)
def test_transcribe_file_cuda_runtime_error_falls_back_to_cpu(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cpu_platform: PlatformInfo,
    caplog: pytest.LogCaptureFixture,
    whisper_model: str,
    expected_model: str,
) -> None:
    info = replace(cpu_platform, cuda_devices=1, cuda_libs_available=True)
    monkeypatch.setattr(platform_info, "detect_platform", lambda: info)
    with (
        patch("faster_whisper.WhisperModel") as model,
        caplog.at_level(logging.WARNING),
    ):
        model.return_value.transcribe.return_value = ([], SimpleNamespace(duration=0.0))
        model.side_effect = [
            RuntimeError("no CUDA-capable device is detected"),
            model.return_value,
        ]
        result = transcriber.transcribe_file(
            tmp_path / "a.m4a",
            config=Settings(device="cuda", whisper_model=whisper_model),
        )
    assert result.model == expected_model
    assert model.call_count == 2
    second_call = model.call_args_list[1]
    assert second_call.kwargs["device"] == "cpu"
    assert second_call.kwargs["compute_type"] == "int8"
    assert transcriber.GPU_FALLBACK_NOTICE in caplog.text
    notices = [r for r in caplog.records if getattr(r, USER_NOTICE, False)]
    assert [record.getMessage() for record in notices] == [
        transcriber.GPU_FALLBACK_NOTICE
    ]


def test_transcribe_file_cuda_runtime_error_on_explicit_cpu_reraises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cpu_platform: PlatformInfo,
) -> None:
    monkeypatch.setattr(platform_info, "detect_platform", lambda: cpu_platform)
    with (
        patch("faster_whisper.WhisperModel", side_effect=RuntimeError("boom")),
        pytest.raises(RuntimeError, match="boom"),
    ):
        transcriber.transcribe_file(tmp_path / "a.m4a", config=Settings(device="cpu"))


@pytest.mark.parametrize(
    "message",
    [
        "Library libcublas.so.12 is not found or cannot be loaded",
        "Library cudnn64_9.dll is not found or cannot be loaded",
        "CUDA failed with error out of memory",
    ],
)
def test_transcribe_file_cuda_library_errors_fall_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cpu_platform: PlatformInfo,
    message: str,
) -> None:
    info = replace(cpu_platform, cuda_devices=1, cuda_libs_available=True)
    monkeypatch.setattr(platform_info, "detect_platform", lambda: info)
    with patch("faster_whisper.WhisperModel") as model:
        model.return_value.transcribe.return_value = ([], SimpleNamespace(duration=0.0))
        model.side_effect = [RuntimeError(message), model.return_value]
        transcriber.transcribe_file(tmp_path / "a.m4a", config=Settings(device="cuda"))
    assert model.call_args_list[1].kwargs["device"] == "cpu"


def test_transcribe_file_cuda_preload_oserror_falls_back_to_cpu(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cpu_platform: PlatformInfo,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # ctypes.CDLL raises OSError when a wheel .so exists but cannot be dlopen()ed.
    info = replace(cpu_platform, cuda_devices=1, cuda_libs_available=True)
    monkeypatch.setattr(platform_info, "detect_platform", lambda: info)

    def broken_preload() -> list[Path]:
        raise OSError("libcudnn_ops.so.9: undefined symbol")

    monkeypatch.setattr(transcriber, "preload_cuda_libraries", broken_preload)
    with (
        patch("faster_whisper.WhisperModel") as model,
        caplog.at_level(logging.WARNING),
    ):
        model.return_value.transcribe.return_value = ([], SimpleNamespace(duration=0.0))
        transcriber.transcribe_file(tmp_path / "a.m4a", config=Settings(device="cuda"))
    assert model.call_count == 1
    assert model.call_args.kwargs["device"] == "cpu"
    assert transcriber.GPU_FALLBACK_NOTICE in caplog.text


def test_transcribe_file_cuda_non_gpu_error_reraises_without_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cpu_platform: PlatformInfo,
    caplog: pytest.LogCaptureFixture,
) -> None:
    info = replace(cpu_platform, cuda_devices=1, cuda_libs_available=True)
    monkeypatch.setattr(platform_info, "detect_platform", lambda: info)
    missing = "Unable to open file 'model.bin' in model '/models/large-v3'"
    with (
        patch(
            "faster_whisper.WhisperModel", side_effect=RuntimeError(missing)
        ) as model,
        caplog.at_level(logging.WARNING),
        pytest.raises(RuntimeError, match="model.bin"),
    ):
        transcriber.transcribe_file(tmp_path / "a.m4a", config=Settings(device="cuda"))
    assert model.call_count == 1
    assert transcriber.GPU_FALLBACK_NOTICE not in caplog.text


def test_transcribe_file_gpu_without_wheels_warns_and_uses_cpu(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cpu_platform: PlatformInfo,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        platform_info, "detect_platform", lambda: replace(cpu_platform, cuda_devices=1)
    )
    with patch("faster_whisper.WhisperModel") as model:
        model.return_value.transcribe.return_value = ([], SimpleNamespace(duration=0.0))
        result = transcriber.transcribe_file(tmp_path / "a.m4a", config=Settings())
    assert result.model == "large-v3-turbo"
    model.assert_called_once_with(
        "large-v3-turbo", device="cpu", compute_type="int8", cpu_threads=8
    )
    assert any(
        record.levelno == logging.WARNING and "uv sync --extra cuda" in record.message
        for record in caplog.records
    )


@pytest.mark.parametrize("source", ["constructor", "environment"])
@pytest.mark.parametrize("model_name", ["small", "large-v3"])
def test_transcribe_file_preserves_explicit_model_on_cpu(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    model_name: str,
) -> None:
    if source == "environment":
        monkeypatch.setenv("SBOBINA_WHISPER_MODEL", model_name)
        config = Settings()
    else:
        config = Settings(whisper_model=model_name)
    with patch("faster_whisper.WhisperModel") as model:
        model.return_value.transcribe.return_value = ([], SimpleNamespace(duration=0.0))
        result = transcriber.transcribe_file(tmp_path / "a.m4a", config=config)
    model.assert_called_once_with(
        model_name, device="cpu", compute_type="int8", cpu_threads=8
    )
    assert result.model == model_name


def test_transcribe_file_per_job_settings_keep_cpu_default_model(
    tmp_path: Path,
) -> None:
    # The web server rebuilds Settings from a full dump plus per-job overrides:
    # every field is then "set", and the CPU default must still apply.
    config = Settings.model_validate({**Settings().model_dump(), "beam_size": 3})
    with patch("faster_whisper.WhisperModel") as model:
        model.return_value.transcribe.return_value = ([], SimpleNamespace(duration=0.0))
        result = transcriber.transcribe_file(tmp_path / "a.m4a", config=config)

    model.assert_called_once_with(
        "large-v3-turbo", device="cpu", compute_type="int8", cpu_threads=8
    )
    assert result.model == "large-v3-turbo"

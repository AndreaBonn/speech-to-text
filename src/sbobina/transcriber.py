import logging
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sbobina import platform_info
from sbobina.cuda_libs import preload_cuda_libraries
from sbobina.models import Segment, Transcript, Word
from sbobina.render import format_timestamp
from sbobina.settings import Settings

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

PROGRESS_EVERY_S = 300.0
ProgressCallback = Callable[[float, float], None]
# Emitted verbatim when a CUDA load fails and the stage falls back to CPU;
# Log records carrying this attribute are meant for the person using the app,
# not only for the log: the web stage runner copies them into progress.json.
USER_NOTICE = "user_notice"
GPU_FALLBACK_NOTICE = "GPU non utilizzabile, trascrizione sul processore"
_CUDA_PRELOAD_SYSTEMS = ("linux", "windows")
# Substrings of ctranslate2 errors raised by the CUDA runtime or its libraries.
# Anything else (missing model.bin, bad model name) is a real error, not a
# reason to fall back to the CPU.
# Missing libraries surface as "Library <name> is not found or cannot be
# loaded", matched through the cublas/cudnn file name.
_CUDA_ERROR_MARKERS = ("cuda", "cudnn", "cublas")


def to_segment(raw_segment: Any) -> Segment | None:
    """Convert a faster-whisper segment; ``None`` when it carries no words."""
    words = tuple(
        Word(
            start=float(word.start),
            end=float(word.end),
            text=word.word,
            probability=float(word.probability),
        )
        for word in raw_segment.words or ()
    )
    if not words:
        return None
    return Segment(
        start=float(raw_segment.start), end=float(raw_segment.end), words=words
    )


def _collect_segments(
    raw_segments: Iterable[Any],
    duration: float,
    on_progress: ProgressCallback | None = None,
) -> tuple[Segment, ...]:
    segments: list[Segment] = []
    next_report = PROGRESS_EVERY_S
    for raw_segment in raw_segments:
        segment = to_segment(raw_segment)
        if segment is not None:
            segments.append(segment)
        if on_progress is not None:
            on_progress(raw_segment.end, duration)
        if raw_segment.end >= next_report:
            logger.info(
                "Trascritti %s di %s",
                format_timestamp(raw_segment.end),
                format_timestamp(duration),
            )
            next_report += PROGRESS_EVERY_S
    return tuple(segments)


def _instantiate(
    model_cls: "type[WhisperModel]", choice: platform_info.RuntimeChoice
) -> "WhisperModel":
    cpu_kwargs = (
        {"cpu_threads": choice.cpu_threads} if choice.cpu_threads is not None else {}
    )
    return model_cls(
        choice.whisper_model,
        device=choice.device,
        compute_type=choice.compute_type,
        **cpu_kwargs,
    )


def _log_runtime(
    info: platform_info.PlatformInfo, choice: platform_info.RuntimeChoice
) -> None:
    logger.info(
        "Runtime: OS=%s device=%s compute_type=%s modello=%s motivo=%s",
        info.system,
        choice.device,
        choice.compute_type,
        choice.whisper_model,
        choice.reason,
    )


def _cpu_fallback_choice(
    info: platform_info.PlatformInfo,
    choice: platform_info.RuntimeChoice,
    config: Settings,
) -> platform_info.RuntimeChoice:
    """Same job, same requested model, but forced onto the CPU after CUDA fails."""
    compute_type = "int8" if "int8" in info.cpu_compute_types else "float32"
    model = (
        config.whisper_model_cpu
        if config.whisper_model == "auto"
        else choice.whisper_model
    )
    return replace(
        choice,
        device="cpu",
        compute_type=compute_type,
        whisper_model=model,
        cpu_threads=config.cpu_threads or info.cpu_count,
        reason="Ripiego su CPU: CUDA non utilizzabile (driver o librerie mancanti)",
    )


def _is_cuda_failure(error: RuntimeError) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in _CUDA_ERROR_MARKERS)


def _preload_cuda_if_needed(
    info: platform_info.PlatformInfo, choice: platform_info.RuntimeChoice
) -> bool:
    """Preload the NVIDIA wheels when CUDA is chosen; ``False`` if that fails."""
    if choice.device != "cuda" or info.system not in _CUDA_PRELOAD_SYSTEMS:
        return True
    try:
        preload_cuda_libraries()
    except OSError:
        # Only NVIDIA libraries are loaded here, so any dlopen failure is a
        # CUDA failure (wrong ABI, missing system dependency).
        logger.exception("Caricamento delle librerie CUDA fallito")
        return False
    return True


def _load_model(
    info: platform_info.PlatformInfo,
    choice: platform_info.RuntimeChoice,
    config: Settings,
) -> tuple["WhisperModel", platform_info.RuntimeChoice]:
    if info.cuda_devices > 0 and not info.cuda_libs_available:
        logger.warning(
            "GPU NVIDIA rilevata ma librerie CUDA non installate: avvia con ./avvia.sh oppure uv sync --extra cuda"
        )
    preload_failed = not _preload_cuda_if_needed(info=info, choice=choice)
    from faster_whisper import WhisperModel  # after preload: ctranslate2 needs cuDNN

    if not preload_failed:
        _log_runtime(info=info, choice=choice)
        try:
            return _instantiate(WhisperModel, choice), choice
        except RuntimeError as error:
            if choice.device != "cuda" or not _is_cuda_failure(error):
                raise
    logger.warning(GPU_FALLBACK_NOTICE, extra={USER_NOTICE: True})
    fallback = _cpu_fallback_choice(info=info, choice=choice, config=config)
    _log_runtime(info=info, choice=fallback)
    return _instantiate(WhisperModel, fallback), fallback


def transcribe_file(
    audio_path: Path, config: Settings, on_progress: ProgressCallback | None = None
) -> Transcript:
    """Run Whisper on ``audio_path`` with word timestamps; VAD per ``config``."""
    detected, choice = platform_info.resolve_for_settings(config=config)
    model, choice = _load_model(info=detected, choice=choice, config=config)
    raw_segments, info = model.transcribe(
        str(audio_path),
        language=config.language,
        beam_size=config.beam_size,
        word_timestamps=True,
        vad_filter=config.vad_filter,
        condition_on_previous_text=config.condition_on_previous_text,
    )
    return Transcript(
        source=str(audio_path),
        model=choice.whisper_model,
        language=config.language,
        duration=float(info.duration),
        segments=_collect_segments(
            raw_segments, duration=float(info.duration), on_progress=on_progress
        ),
    )

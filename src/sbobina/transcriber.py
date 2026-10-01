import logging
from collections.abc import Callable, Iterable
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


def _load_model(
    info: platform_info.PlatformInfo, choice: platform_info.RuntimeChoice
) -> "WhisperModel":
    if info.cuda_devices > 0 and not info.cuda_libs_available:
        logger.warning(
            "GPU NVIDIA rilevata ma librerie CUDA non installate: avvia con ./avvia.sh oppure uv sync --extra cuda"
        )
    if choice.device == "cuda" and info.system == "linux":
        preload_cuda_libraries()
    from faster_whisper import WhisperModel  # after preload: ctranslate2 needs cuDNN

    logger.info(
        "Runtime: OS=%s device=%s compute_type=%s modello=%s motivo=%s",
        info.system,
        choice.device,
        choice.compute_type,
        choice.whisper_model,
        choice.reason,
    )
    cpu_kwargs = (
        {"cpu_threads": choice.cpu_threads} if choice.cpu_threads is not None else {}
    )
    return WhisperModel(
        choice.whisper_model,
        device=choice.device,
        compute_type=choice.compute_type,
        **cpu_kwargs,
    )


def transcribe_file(
    audio_path: Path, config: Settings, on_progress: ProgressCallback | None = None
) -> Transcript:
    """Run Whisper on ``audio_path`` with word timestamps; VAD per ``config``."""
    detected, choice = platform_info.resolve_for_settings(config=config)
    model = _load_model(info=detected, choice=choice)
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

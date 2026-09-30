import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sbobina.cuda_libs import preload_cuda_libraries
from sbobina.models import Segment, Transcript, Word
from sbobina.render import format_timestamp
from sbobina.settings import Settings

logger = logging.getLogger(__name__)

PROGRESS_EVERY_S = 300.0


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
    raw_segments: Iterable[Any], duration: float
) -> tuple[Segment, ...]:
    segments: list[Segment] = []
    next_report = PROGRESS_EVERY_S
    for raw_segment in raw_segments:
        segment = to_segment(raw_segment)
        if segment is not None:
            segments.append(segment)
        if raw_segment.end >= next_report:
            logger.info(
                "Trascritti %s di %s",
                format_timestamp(raw_segment.end),
                format_timestamp(duration),
            )
            next_report += PROGRESS_EVERY_S
    return tuple(segments)


def transcribe_file(audio_path: Path, config: Settings) -> Transcript:
    """Run Whisper on ``audio_path`` with word timestamps; VAD per ``config``."""
    preload_cuda_libraries()
    from faster_whisper import WhisperModel  # after preload: ctranslate2 needs cuDNN

    logger.info("Carico il modello %s su %s", config.whisper_model, config.device)
    model = WhisperModel(
        config.whisper_model, device=config.device, compute_type=config.compute_type
    )
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
        model=config.whisper_model,
        language=config.language,
        duration=float(info.duration),
        segments=_collect_segments(raw_segments, duration=float(info.duration)),
    )

"""AssemblyAI sentences reply -> `Transcript` (pure, no I/O).

Sentences become segments (ADR-003 D6, K3): grouping words by pause would
make paragraph-sized segments, and `render.group_paragraphs` and
`cleanup.py` both expect sentence-sized ones, as Whisper produces.
"""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from sbobina.models import Segment, Transcript, Word

_MS_PER_S = 1000.0


class _ReplyWord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    start: int
    end: int
    confidence: float


class _ReplySentence(BaseModel):
    model_config = ConfigDict(extra="ignore")

    start: int
    end: int
    words: list[_ReplyWord]


class _SentencesReply(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sentences: list[_ReplySentence]


@dataclass(frozen=True, kw_only=True)
class TranscriptMeta:
    source: str
    speech_model: str
    language: str
    duration: float


def _to_word(word: _ReplyWord) -> Word:
    # Whisper words carry their leading space; downstream joins rely on it.
    return Word(
        start=word.start / _MS_PER_S,
        end=word.end / _MS_PER_S,
        text=f" {word.text}",
        probability=word.confidence,
    )


def _to_segment(sentence: _ReplySentence) -> Segment | None:
    if not sentence.words:
        return None
    words = tuple(_to_word(word=word) for word in sentence.words)
    return Segment(start=words[0].start, end=words[-1].end, words=words)


def to_transcript(payload: dict[str, Any], meta: TranscriptMeta) -> Transcript:
    """Validate the `/sentences` reply and convert it.

    Raises
    ------
    pydantic.ValidationError
        The reply misses a field the conversion needs (e.g. `confidence`).
    """
    reply = _SentencesReply.model_validate(payload)
    segments = (_to_segment(sentence=sentence) for sentence in reply.sentences)
    return Transcript(
        source=meta.source,
        model=f"assemblyai:{meta.speech_model}",
        language=meta.language,
        duration=meta.duration,
        segments=tuple(segment for segment in segments if segment is not None),
    )

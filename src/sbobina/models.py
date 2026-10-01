import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str
    probability: float
    corrected_from: str | None = None  # what Whisper heard, when the LLM fixed it


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    words: tuple[Word, ...]

    @property
    def text(self) -> str:
        return "".join(word.text for word in self.words).strip()


@dataclass(frozen=True)
class Transcript:
    source: str
    model: str
    language: str
    duration: float
    segments: tuple[Segment, ...]

    @property
    def words(self) -> tuple[Word, ...]:
        return tuple(word for segment in self.segments for word in segment.words)

    @property
    def text(self) -> str:
        return " ".join(segment.text for segment in self.segments)


def transcript_to_json(transcript: Transcript) -> str:
    return json.dumps(asdict(transcript), ensure_ascii=False, indent=1)


def save_transcript(transcript: Transcript, path: Path) -> None:
    path.write_text(transcript_to_json(transcript), encoding="utf-8")


def load_transcript(path: Path) -> Transcript:
    raw = json.loads(path.read_text(encoding="utf-8"))
    segments = tuple(
        Segment(
            start=seg["start"],
            end=seg["end"],
            words=tuple(Word(**word) for word in seg["words"]),
        )
        for seg in raw["segments"]
    )
    return Transcript(
        source=raw["source"],
        model=raw["model"],
        language=raw["language"],
        duration=raw["duration"],
        segments=segments,
    )

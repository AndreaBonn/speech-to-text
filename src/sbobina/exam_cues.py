import re
from dataclasses import dataclass
from typing import Literal

from sbobina.models import Transcript

CueLevel = Literal["strong", "weak"]
# v2 adds the enclitic forms ("ricordatevelo"), missed by v1 in a real lecture.
STRONG_PATTERNS_V2 = (
    "all'esame",
    "vi chiederò",
    "domanda d'esame",
    "ricordatevi",
    "ricordatevelo",
    "ricordatevela",
    "ricordateveli",
    "ricordatevele",
    "segnatevelo",
    "segnatevela",
    "segnateveli",
    "segnatevele",
    "lo chiedo",
)
WEAK_PATTERNS_V1 = ("importante", "fondamentale", "attenzione")
NEGATIVE_PATTERNS_V1 = ("l'importante è che",)
# A dot glued to the next character ("art.1140", "window.x") is not a sentence end.
SENTENCE_SEPARATOR = re.compile(r"[.!?]+(?=\s|$)")


def _whole_words(patterns: tuple[str, ...]) -> re.Pattern[str]:
    # Word boundaries keep "disattenzione" and "glielo chiedo" out.
    alternatives = "|".join(re.escape(pattern) for pattern in patterns)
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)")


STRONG_RE = _whole_words(patterns=STRONG_PATTERNS_V2)
WEAK_RE = _whole_words(patterns=WEAK_PATTERNS_V1)
NEGATIVE_RE = _whole_words(patterns=NEGATIVE_PATTERNS_V1)


@dataclass(frozen=True)
class ExamCue:
    job_id: str
    segment_index: int
    quote: str
    start: float
    level: CueLevel

    def __post_init__(self) -> None:
        if not self.quote.strip():
            raise ValueError("quote must not be empty")
        if self.start < 0:
            raise ValueError("start must not be negative")


def classify_sentence(text: str) -> CueLevel | None:
    normalized = text.lower().replace("’", "'")
    if STRONG_RE.search(normalized):
        return "strong"
    # Negative contexts only rule out the weak "importante" of "l'importante è che".
    if NEGATIVE_RE.search(normalized):
        return None
    if WEAK_RE.search(normalized):
        return "weak"
    return None


def find_exam_cues(transcript: Transcript, job_id: str) -> tuple[ExamCue, ...]:
    cues = []
    for segment_index, segment in enumerate(transcript.segments):
        for sentence in SENTENCE_SEPARATOR.split(string=segment.text):
            quote = sentence.strip()
            level = classify_sentence(text=quote)
            if level is None:
                continue
            cues.append(
                ExamCue(
                    job_id=job_id,
                    segment_index=segment_index,
                    quote=quote,
                    start=segment.start,
                    level=level,
                )
            )
    return tuple(cues)

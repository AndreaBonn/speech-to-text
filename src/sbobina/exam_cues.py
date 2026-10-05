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
# A cue this short ("e all'esame", "ricordatevelo") says that something matters,
# not what: the words that follow carry it (F33). Display only, never an anchor.
SHORT_QUOTE_WORDS = 6
FOLLOWUP_WORDS = 30


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
    followup: str = ""

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


def _sentences_with_rest(text: str) -> list[tuple[str, str]]:
    """Each sentence with the raw text after its end, punctuation included.

    Same pieces as SENTENCE_SEPARATOR.split, which drops the punctuation a
    followup needs to read as sentences rather than one run-on line.
    """
    pieces, start = [], 0
    for match in SENTENCE_SEPARATOR.finditer(string=text):
        pieces.append((text[start : match.start()], text[match.end() :]))
        start = match.end()
    pieces.append((text[start:], ""))
    return pieces


def _followup(transcript: Transcript, segment_index: int, rest: str) -> str:
    words = rest.split()
    for segment in transcript.segments[segment_index + 1 :]:
        if len(words) >= FOLLOWUP_WORDS:
            break
        words.extend(segment.text.split())
    return " ".join(words[:FOLLOWUP_WORDS])


def find_exam_cues(transcript: Transcript, job_id: str) -> tuple[ExamCue, ...]:
    cues = []
    for segment_index, segment in enumerate(transcript.segments):
        for sentence, rest in _sentences_with_rest(text=segment.text):
            quote = sentence.strip()
            level = classify_sentence(text=quote)
            if level is None:
                continue
            followup = ""
            if len(quote.split()) < SHORT_QUOTE_WORDS:
                followup = _followup(
                    transcript=transcript, segment_index=segment_index, rest=rest
                )
            cues.append(
                ExamCue(
                    job_id=job_id,
                    segment_index=segment_index,
                    quote=quote,
                    start=segment.start,
                    level=level,
                    followup=followup,
                )
            )
    return tuple(cues)

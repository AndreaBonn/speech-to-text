import re
from dataclasses import dataclass

import jiwer

_TIMESTAMP = re.compile(r"\[\d{2}:\d{2}:\d{2}\]")
_UNCERTAIN_MARKER = re.compile(r"\[\?|\?\]")
_APOSTROPHES = re.compile(r"['’`]")
_NON_WORD = re.compile(r"[^\w\s]")


@dataclass(frozen=True)
class WerReport:
    wer: float
    reference_words: int
    substitutions: int
    deletions: int
    insertions: int


def normalize_text(text: str) -> str:
    """Lowercase, drop our own markup and punctuation; accents are kept (è ≠ e)."""
    text = _TIMESTAMP.sub(" ", text)
    text = _UNCERTAIN_MARKER.sub("", text)
    text = _APOSTROPHES.sub(" ", text.lower())
    text = _NON_WORD.sub(" ", text)
    return " ".join(text.split())


def compute_wer(reference: str, hypothesis: str) -> WerReport:
    normalized_reference = normalize_text(reference)
    if not normalized_reference:
        raise ValueError("Il testo di riferimento è vuoto dopo la normalizzazione")
    output = jiwer.process_words(normalized_reference, normalize_text(hypothesis))
    return WerReport(
        wer=output.wer,
        reference_words=output.hits + output.substitutions + output.deletions,
        substitutions=output.substitutions,
        deletions=output.deletions,
        insertions=output.insertions,
    )

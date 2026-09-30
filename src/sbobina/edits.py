import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from difflib import SequenceMatcher

from sbobina.models import Word
from sbobina.wer import normalize_text

# Guards that keep the LLM a proofreader, not an editor. The model quotes a
# whole sentence as anchor; only word substitutions inside it are applied, at
# most MAX_CHANGED_WORDS, each sounding like what Whisper heard. On real
# proposals 0.6 keeps "comunicato"->"giudicato" (0.63) and rejects meaning
# flips such as "ammesso"->"escluso" (0.57) or "propria"->"Corte" (0.17).
MAX_ANCHOR_TOKENS = 30
MAX_CHANGED_WORDS = 3
MIN_SIMILARITY = 0.6
CORRECTED_PROBABILITY = 1.0
_LEADING = re.compile(r"^\s*[\"'’“«(\[¿]*")
_TRAILING = re.compile(r"[\"”».,;:!?)\]…]*$")
_EDGE_PUNCTUATION = " \"'’“”«».,;:!?()[]…"


@dataclass(frozen=True)
class Edit:
    original: str
    corrected: str


@dataclass(frozen=True)
class AppliedCorrection:
    start: float
    original: str
    corrected: str


@dataclass(frozen=True)
class RejectedEdit:
    start: float
    original: str
    corrected: str
    reason: str
    similarity: float | None = None  # set when rejected for not sounding alike


@dataclass(frozen=True)
class _Rejection:
    reason: str
    similarity: float | None = None


@dataclass(frozen=True)
class EditResult:
    words: tuple[Word, ...]
    sources: tuple[int, ...]  # index of the original word each output word comes from
    applied: list[AppliedCorrection]
    rejected: list[RejectedEdit]


@dataclass(frozen=True)
class _Replacement:
    first: int  # word indices relative to the anchor span, inclusive
    last: int
    text: str


def _tokens(text: str) -> list[str]:
    return normalize_text(text).split()


def find_spans(words: tuple[Word, ...], target: list[str]) -> list[tuple[int, int]]:
    """Return ``[i, j)`` word ranges whose normalized tokens equal ``target``."""
    word_tokens = [_tokens(word.text) for word in words]
    spans = []
    for i in range(len(words)):
        if not word_tokens[i]:
            continue
        collected: list[str] = []
        j = i
        while j < len(words) and len(collected) < len(target):
            collected += word_tokens[j]
            j += 1
        if collected == target:
            spans.append((i, j))
    return spans


_Opcode = tuple[str, int, int, int, int]


@dataclass(frozen=True)
class _WordDiff:
    keyed: list[
        tuple[int, str]
    ]  # (index in span, normalized word), punctuation-only dropped
    corrected_raw: list[str]
    corrected_norm: list[str]
    changes: Sequence[_Opcode]


def _diff_words(span: tuple[Word, ...], corrected: str) -> _WordDiff:
    keyed = [
        (k, normalize_text(w.text))
        for k, w in enumerate(span)
        if normalize_text(w.text)
    ]
    original_norm = [n for _, n in keyed]
    corrected_raw = [w for w in corrected.split() if normalize_text(w)]
    corrected_norm = [normalize_text(w) for w in corrected_raw]
    matcher = SequenceMatcher(None, original_norm, corrected_norm, autojunk=False)
    # Whisper splits elisions (" all" + "'ambito") while the model writes
    # "all'ambito": same tokens, different word boundaries, not a correction.
    changes = [
        (tag, i1, i2, j1, j2)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if " ".join(original_norm[i1:i2]).split()
        != " ".join(corrected_norm[j1:j2]).split()
    ]
    return _WordDiff(keyed, corrected_raw, corrected_norm, changes)


def _plan_replacements(
    span: tuple[Word, ...], corrected: str
) -> list[_Replacement] | _Rejection:
    """Turn the word diff into replacements, or explain why the edit is refused."""
    diff = _diff_words(span, corrected)
    # A replace may shrink (Whisper split one word in two: "con leghe" ->
    # "collega") but never grow: a longer correction adds unspoken words.
    if any(
        tag != "replace" or j2 - j1 > i2 - i1 for tag, i1, i2, j1, j2 in diff.changes
    ):
        return _Rejection("aggiunge o toglie parole")
    if sum(i2 - i1 for _, i1, i2, _, _ in diff.changes) > MAX_CHANGED_WORDS:
        return _Rejection("modifica troppo lunga")
    replacements = []
    for _, i1, i2, j1, j2 in diff.changes:
        before = " ".join(n for _, n in diff.keyed[i1:i2])
        similarity = SequenceMatcher(
            None, before, " ".join(diff.corrected_norm[j1:j2])
        ).ratio()
        if similarity < MIN_SIMILARITY:
            return _Rejection("troppo diverso dal suono originale", similarity)
        text = " ".join(diff.corrected_raw[j1:j2])
        replacements.append(
            _Replacement(diff.keyed[i1][0], diff.keyed[i2 - 1][0], text)
        )
    return replacements


def _replacement_text(first: Word, last: Word, corrected: str) -> str:
    leading = _LEADING.match(first.text)
    trailing = _TRAILING.search(last.text)
    body = corrected.strip(_EDGE_PUNCTUATION)
    return f"{leading.group() if leading else ''}{body}{trailing.group() if trailing else ''}"


def _heard_text(span: tuple[Word, ...]) -> str:
    """What Whisper heard over ``span``, even if some words were already corrected."""
    heard = (w.corrected_from or w.text.strip(_EDGE_PUNCTUATION) for w in span)
    return " ".join(part for part in heard if part)


def _substitute(
    result: EditResult, first: int, last: int, corrected: str
) -> EditResult:
    words = result.words
    text = _replacement_text(words[first], words[last], corrected)
    original = "".join(w.text for w in words[first : last + 1]).strip()
    merged = Word(
        start=words[first].start,
        end=words[last].end,
        text=text,
        probability=CORRECTED_PROBABILITY,
        corrected_from=_heard_text(words[first : last + 1]),
    )
    return EditResult(
        words=(*words[:first], merged, *words[last + 1 :]),
        sources=(*result.sources[: first + 1], *result.sources[last + 1 :]),
        applied=[
            *result.applied,
            AppliedCorrection(merged.start, original, text.strip()),
        ],
        rejected=result.rejected,
    )


def _apply_one(result: EditResult, edit: Edit, chunk_start: float) -> EditResult:
    def reject(
        reason: str, at: float = chunk_start, similarity: float | None = None
    ) -> EditResult:
        rejected = RejectedEdit(at, edit.original, edit.corrected, reason, similarity)
        return replace(result, rejected=[*result.rejected, rejected])

    anchor = _tokens(edit.original)
    if anchor == _tokens(edit.corrected):
        return result
    if len(anchor) > MAX_ANCHOR_TOKENS:
        return reject("modifica troppo lunga")
    spans = find_spans(result.words, anchor)
    if len(spans) != 1:
        return reject(
            "testo originale non trovato" if not spans else "testo originale ambiguo"
        )
    start, end = spans[0]
    plan = _plan_replacements(result.words[start:end], edit.corrected)
    if isinstance(plan, _Rejection):
        return reject(
            plan.reason, at=result.words[start].start, similarity=plan.similarity
        )
    for step in reversed(plan):  # right to left keeps earlier indices valid
        result = _substitute(result, start + step.first, start + step.last, step.text)
    return result


def apply_edits(words: tuple[Word, ...], edits: list[Edit]) -> EditResult:
    """Apply LLM-proposed edits that pass the guards; the rest are reported."""
    result = EditResult(
        words=words, sources=tuple(range(len(words))), applied=[], rejected=[]
    )
    chunk_start = words[0].start if words else 0.0
    for edit in edits:
        result = _apply_one(result, edit, chunk_start)
    return result

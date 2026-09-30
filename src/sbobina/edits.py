import re
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


def _plan_replacements(
    span: tuple[Word, ...], corrected: str
) -> list[_Replacement] | str:
    """Diff anchor and correction word by word; return replacements or a reject reason."""
    keyed = [
        (k, normalize_text(w.text))
        for k, w in enumerate(span)
        if normalize_text(w.text)
    ]
    corrected_raw = [w for w in corrected.split() if normalize_text(w)]
    corrected_norm = [normalize_text(w) for w in corrected_raw]
    matcher = SequenceMatcher(
        None, [n for _, n in keyed], corrected_norm, autojunk=False
    )
    original_norm = [n for _, n in keyed]
    # Whisper splits elisions (" all" + "'ambito") while the model writes
    # "all'ambito": same tokens, different word boundaries, not a correction.
    changes = [
        (tag, i1, i2, j1, j2)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if " ".join(original_norm[i1:i2]).split()
        != " ".join(corrected_norm[j1:j2]).split()
    ]
    # A replace may shrink (Whisper split one word in two: "con leghe" ->
    # "collega") but never grow: a longer correction adds unspoken words.
    if any(tag != "replace" or j2 - j1 > i2 - i1 for tag, i1, i2, j1, j2 in changes):
        return "aggiunge o toglie parole"
    if sum(i2 - i1 for _, i1, i2, _, _ in changes) > MAX_CHANGED_WORDS:
        return "modifica troppo lunga"
    replacements = []
    for _, i1, i2, j1, j2 in changes:
        before = " ".join(n for _, n in keyed[i1:i2])
        if (
            SequenceMatcher(None, before, " ".join(corrected_norm[j1:j2])).ratio()
            < MIN_SIMILARITY
        ):
            return "troppo diverso dal suono originale"
        replacements.append(
            _Replacement(keyed[i1][0], keyed[i2 - 1][0], " ".join(corrected_raw[j1:j2]))
        )
    return replacements


def _replacement_text(first: Word, last: Word, corrected: str) -> str:
    leading = _LEADING.match(first.text)
    trailing = _TRAILING.search(last.text)
    body = corrected.strip(_EDGE_PUNCTUATION)
    return f"{leading.group() if leading else ''}{body}{trailing.group() if trailing else ''}"


def _substitute(
    result: EditResult, first: int, last: int, corrected: str
) -> EditResult:
    words = result.words
    text = _replacement_text(words[first], words[last], corrected)
    merged = Word(words[first].start, words[last].end, text, CORRECTED_PROBABILITY)
    original = "".join(w.text for w in words[first : last + 1]).strip()
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
    def reject(reason: str) -> EditResult:
        rejected = RejectedEdit(chunk_start, edit.original, edit.corrected, reason)
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
    if isinstance(plan, str):
        return reject(plan)
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

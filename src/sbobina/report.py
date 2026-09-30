from pathlib import Path

from sbobina.correction import CorrectionResult
from sbobina.edits import MIN_SIMILARITY, RejectedEdit
from sbobina.models import Segment
from sbobina.render import format_timestamp

# Only proposals that missed the sound-alike guard by a little are worth a
# student's time; measured on a real lecture, the rest were mostly rewrites
# ("calpestano il suono dell'ombra" -> "che nascono, vivono e muoiono").
SUGGESTION_MIN_SIMILARITY = 0.5
NOT_ALIKE_REASON = "troppo diverso dal suono originale"
EMPTY_LIST = "Niente da segnalare."


def _section(title: str, items: list[str]) -> list[str]:
    return [f"## {title}", "", *(items or [EMPTY_LIST]), ""]


def is_near_miss(rejected: RejectedEdit) -> bool:
    return (
        rejected.reason == NOT_ALIKE_REASON
        and rejected.similarity is not None
        and SUGGESTION_MIN_SIMILARITY <= rejected.similarity < MIN_SIMILARITY
    )


def _header(
    result: CorrectionResult, model: str, suggestions: int, removed: int
) -> list[str]:
    lines = [
        f"# Correzioni: {Path(result.transcript.source).name}",
        "",
        (
            f"Modello {model}. Applicate {len(result.applied)}, suggerimenti da "
            f"verificare {suggestions}, riempitivi tolti {removed}."
        ),
        "",
    ]
    if result.interrupted_at is not None:
        stop = format_timestamp(result.interrupted_at)
        lines += [
            f"Correzione interrotta a [{stop}]: da lì in poi il testo non è corretto.",
            "",
        ]
    return lines


def render_corrections_report(
    result: CorrectionResult, model: str, removed: list[Segment]
) -> str:
    """Markdown list of every change made by ``sbobina correggi``, with timestamps."""
    suggestions = [r for r in result.rejected if is_near_miss(r)]
    lines = [
        *_header(result, model, suggestions=len(suggestions), removed=len(removed)),
        *_section(
            "Correzioni applicate",
            [
                f"- [{format_timestamp(a.start)}] {a.original} → **{a.corrected}**"
                for a in result.applied
            ],
        ),
        *_section(
            "Suggerimenti da verificare",
            [
                f"- [{format_timestamp(s.start)}] «{s.original}» → «{s.corrected}»"
                for s in suggestions
            ],
        ),
        *_section(
            "Paragrafi non corretti",
            [
                f"- [{format_timestamp(start)}] risposta del modello non valida, paragrafo non corretto"
                for start in result.failed_chunks
            ],
        ),
        *_section(
            "Riempitivi tolti nelle pause",
            [f"- [{format_timestamp(s.start)}] {s.text}" for s in removed],
        ),
    ]
    return "\n".join(lines)

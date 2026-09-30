from pathlib import Path

from sbobina.edits import AppliedCorrection, RejectedEdit
from sbobina.models import Segment
from sbobina.render import format_timestamp

# A proposal whose quoted text is not in the transcript carries no position to
# re-listen: it is model noise, not a suggestion worth the reader's time.
UNACTIONABLE_REASONS = frozenset({"testo originale non trovato"})
EMPTY_LIST = "Nessuna."


def _section(title: str, items: list[str]) -> list[str]:
    return [f"## {title}", "", *(items or [EMPTY_LIST]), ""]


def render_corrections_report(
    source: str,
    model: str,
    applied: list[AppliedCorrection],
    rejected: list[RejectedEdit],
    removed: list[Segment],
) -> str:
    """Markdown list of every change made by ``sbobina correggi``, with timestamps."""
    suggestions = [r for r in rejected if r.reason not in UNACTIONABLE_REASONS]
    lines = [
        f"# Correzioni: {Path(source).name}",
        "",
        (
            f"Modello {model}. Applicate {len(applied)}, suggerimenti da verificare "
            f"{len(suggestions)}, riempitivi tolti {len(removed)}."
        ),
        "",
        *_section(
            "Correzioni applicate",
            [
                f"- [{format_timestamp(a.start)}] {a.original} → **{a.corrected}**"
                for a in applied
            ],
        ),
        *_section(
            "Suggerimenti non applicati (da verificare)",
            [
                f"- [{format_timestamp(s.start)}] «{s.original}» → «{s.corrected}» ({s.reason})"
                for s in suggestions
            ],
        ),
        *_section(
            "Riempitivi tolti nelle pause",
            [f"- [{format_timestamp(s.start)}] {s.text}" for s in removed],
        ),
    ]
    return "\n".join(lines)

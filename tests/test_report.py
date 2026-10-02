from conftest import make_segment, make_transcript, make_word

from sbobina.correction import CorrectionResult
from sbobina.edits import AppliedCorrection, RejectedEdit
from sbobina.report import render_corrections_report

TRANSCRIPT = make_transcript([make_segment([make_word(" testo", 0.0)])])
NOT_ALIKE = "troppo diverso dal suono originale"


def _rejected(
    original: str, reason: str, similarity: float | None = None
) -> RejectedEdit:
    return RejectedEdit(
        start=120.0,
        original=original,
        corrected="x",
        reason=reason,
        similarity=similarity,
    )


def test_report_lists_applied_near_miss_suggestions_and_removed_fillers() -> None:
    result = CorrectionResult(
        transcript=TRANSCRIPT,
        applied=[
            AppliedCorrection(start=65.0, original="legione", corrected="lesione")
        ],
        rejected=[_rejected("tutela giustiziaria", NOT_ALIKE, 0.59)],
    )

    report = render_corrections_report(
        result,
        model="qwen3.5:9b",
        removed=[make_segment([make_word(" Grazie.", 383.0)])],
    )

    assert "# Correzioni: lezione.m4a" in report
    assert "Applicate 1, suggerimenti da verificare 1, riempitivi tolti 1" in report
    assert "- [00:01:05] legione → **lesione**" in report
    assert "- [00:02:00] «tutela giustiziaria» → «x»" in report
    assert "- [00:06:23] Grazie." in report


def test_report_keeps_only_suggestions_just_below_the_similarity_threshold() -> None:
    result = CorrectionResult(
        transcript=TRANSCRIPT,
        applied=[],
        rejected=[
            _rejected("vicino", NOT_ALIKE, 0.55),
            _rejected("lontano", NOT_ALIKE, 0.30),
            _rejected("aggiunta", "aggiunge o toglie parole"),
            _rejected("ambiguo", "testo originale ambiguo"),
        ],
    )

    report = render_corrections_report(result, model="m", removed=[])

    assert "«vicino»" in report
    assert "«lontano»" not in report
    assert "«aggiunta»" not in report
    assert "«ambiguo»" not in report


def test_report_lists_skipped_paragraphs_and_interruption() -> None:
    result = CorrectionResult(
        transcript=TRANSCRIPT,
        applied=[],
        rejected=[],
        failed_chunks=[754.0],
        interrupted_at=3000.0,
    )

    report = render_corrections_report(result, model="m", removed=[])

    assert (
        "- [00:12:34] risposta del modello non valida, paragrafo non corretto" in report
    )
    assert "Correzione interrotta a [00:50:00]" in report


def test_report_complete_run_has_no_interruption_line_and_says_when_lists_are_empty() -> (
    None
):
    result = CorrectionResult(transcript=TRANSCRIPT, applied=[], rejected=[])

    report = render_corrections_report(result, model="m", removed=[])

    assert "interrotta" not in report
    assert report.count("Niente da segnalare.") == 4


def test_report_suggestion_bounds_include_lower_and_exclude_threshold() -> None:
    result = CorrectionResult(
        transcript=TRANSCRIPT,
        applied=[],
        rejected=[
            _rejected("limite_basso", NOT_ALIKE, 0.5),
            _rejected("soglia", NOT_ALIKE, 0.6),
        ],
    )

    report = render_corrections_report(result, model="m", removed=[])

    assert "«limite_basso»" in report
    assert "«soglia»" not in report

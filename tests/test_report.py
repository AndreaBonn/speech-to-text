from conftest import make_segment, make_word

from sbobina.edits import AppliedCorrection, RejectedEdit
from sbobina.report import render_corrections_report


def test_report_lists_applied_suggestions_and_removed_fillers_with_timestamps() -> None:
    report = render_corrections_report(
        source="lezione.m4a",
        model="qwen3.5:9b",
        applied=[
            AppliedCorrection(start=65.0, original="legione", corrected="lesione")
        ],
        rejected=[
            RejectedEdit(
                start=120.0,
                original="caso comune",
                corrected="caso concreto",
                reason="troppo diverso dal suono originale",
            )
        ],
        removed=[make_segment([make_word(" Grazie.", 383.0)])],
    )

    assert "# Correzioni: lezione.m4a" in report
    assert "Applicate 1, suggerimenti da verificare 1, riempitivi tolti 1" in report
    assert "- [00:01:05] legione → **lesione**" in report
    assert (
        "- [00:02:00] «caso comune» → «caso concreto» (troppo diverso dal suono originale)"
        in report
    )
    assert "- [00:06:23] Grazie." in report


def test_report_skips_not_found_suggestions_and_says_when_lists_are_empty() -> None:
    report = render_corrections_report(
        source="lezione.m4a",
        model="qwen3.5:9b",
        applied=[],
        rejected=[
            RejectedEdit(
                start=0.0,
                original="x",
                corrected="y",
                reason="testo originale non trovato",
            )
        ],
        removed=[],
    )

    assert "Applicate 0, suggerimenti da verificare 0, riempitivi tolti 0" in report
    assert "«x»" not in report
    assert report.count("Nessuna.") == 3

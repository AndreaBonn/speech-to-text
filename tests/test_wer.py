import pytest

from sbobina.wer import compute_wer, normalize_text


def test_normalize_text_lowercases_and_strips_punctuation_keeping_accents() -> None:
    assert normalize_text("Perché, è così!") == "perché è così"


def test_normalize_text_splits_elisions_and_unifies_apostrophes() -> None:
    assert normalize_text("dell’equazione dell'atomo") == "dell equazione dell atomo"


def test_normalize_text_removes_timestamps_and_uncertainty_markers() -> None:
    assert normalize_text("[00:01:02] di [?Sennberg?],") == "di sennberg"


def test_compute_wer_counts_substitution_and_insertion() -> None:
    report = compute_wer(
        reference="il teorema di Noether collega simmetrie",
        hypothesis="il teorema di Noether con leghe simmetrie",
    )

    assert report.reference_words == 6
    assert (report.substitutions, report.deletions, report.insertions) == (1, 0, 1)
    assert report.wer == pytest.approx(2 / 6)


def test_compute_wer_counts_deletion() -> None:
    report = compute_wer(
        reference="il teorema di Noether", hypothesis="il teorema Noether"
    )

    assert (report.substitutions, report.deletions, report.insertions) == (0, 1, 0)
    assert report.wer == pytest.approx(1 / 4)


def test_compute_wer_identical_texts_is_zero_ignoring_case_and_punctuation() -> None:
    report = compute_wer(reference="Ciao, mondo.", hypothesis="ciao mondo")

    assert report.wer == 0.0


def test_compute_wer_empty_reference_raises() -> None:
    with pytest.raises(ValueError, match="riferimento"):
        compute_wer(reference=" ,. ", hypothesis="qualcosa")

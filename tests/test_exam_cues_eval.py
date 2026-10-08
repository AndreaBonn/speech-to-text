from typing import Any

import pytest

from sbobina.exam_cues import CueLevel, ExamCue
from sbobina.exam_cues_eval import aggregate, compare_strong, ratio, redetect


def _row(source: str, predicted: str | None, label: str) -> dict[str, Any]:
    return {"job_id": "a", "source": source, "predicted": predicted, "label": label}


def _cue(quote: str, level: CueLevel = "strong") -> ExamCue:
    return ExamCue(job_id="a", segment_index=0, quote=quote, start=0.0, level=level)


def test_ratio_zero_denominator_returns_none() -> None:
    assert ratio(numerator=3, denominator=4) == 0.75
    assert ratio(numerator=0, denominator=0) is None


def test_aggregate_unlabeled_rows_counted_but_excluded_from_precision() -> None:
    rows = [
        _row(source="detector", predicted="strong", label="strong"),
        _row(source="detector", predicted="strong", label="none"),
        _row(source="detector", predicted="strong", label=""),
        _row(source="wide_net", predicted=None, label="weak"),
    ]

    report = aggregate(rows=rows)

    assert report["precision"]["strong"] == {"correct": 1, "total": 2, "value": 0.5}
    assert report["wide_net_recall"]["value"] == pytest.approx(1 / 2)
    assert report["counts"]["unlabeled"] == 1
    assert report["counts"]["total"] == 4


def test_compare_strong_ignores_weak_and_normalizes_case() -> None:
    report = compare_strong(
        cues_a=(
            _cue(quote="Ricordatevi  il termine"),
            _cue(quote="Importante", level="weak"),
        ),
        cues_b=(_cue(quote="ricordatevi il termine"), _cue(quote="Segnatevelo")),
    )

    assert report["common"] == ["ricordatevi il termine"]
    assert report["only_b"] == ["segnatevelo"]
    assert report["only_a"] == []
    assert report["overlap"] == 0.5


def test_redetect_replaces_stored_predictions_with_fresh_cues() -> None:
    # F39: a pattern change is invisible if predictions come from the export.
    rows = [
        {
            "job_id": "a",
            "segment_index": 0,
            "quote": "Ricordatevelo",
            "source": "wide_net",
            "predicted": None,
            "label": "strong",
        },
        {
            "job_id": "a",
            "segment_index": 1,
            "quote": "questo è importante",
            "source": "detector",
            "predicted": "weak",
            "label": "none",
        },
    ]
    cues = {
        "a": (
            _cue(quote="ricordatevelo"),
            ExamCue(
                job_id="a",
                segment_index=2,
                quote="ma attenzione",
                start=0.0,
                level="weak",
            ),
        )
    }

    fresh, unlabeled = redetect(rows=rows, cues=cues)

    assert [(row["source"], row["predicted"]) for row in fresh] == [
        ("detector", "strong"),
        ("wide_net", None),
    ]
    assert [row["label"] for row in fresh] == ["strong", "none"]
    assert unlabeled == [
        {"job_id": "a", "segment_index": 2, "quote": "ma attenzione", "level": "weak"}
    ]
    assert rows[0]["predicted"] is None


def test_redetect_leaves_rows_of_unmeasured_jobs_untouched() -> None:
    row = {
        "job_id": "b",
        "segment_index": 0,
        "quote": "x",
        "source": "detector",
        "predicted": "strong",
        "label": "none",
    }

    fresh, unlabeled = redetect(rows=[row], cues={"a": ()})

    assert fresh == [row]
    assert unlabeled == []


def test_redetect_repeated_cue_returns_extra_occurrence_as_unlabeled() -> None:
    row = {
        "job_id": "a",
        "segment_index": 0,
        "quote": "ma attenzione",
        "source": "wide_net",
        "predicted": None,
        "label": "weak",
    }
    repeated = ExamCue(
        job_id="a", segment_index=0, quote="ma attenzione", start=0.0, level="weak"
    )

    fresh, unlabeled = redetect(rows=[row], cues={"a": (repeated, repeated)})

    assert [r["predicted"] for r in fresh] == ["weak"]
    assert unlabeled == [
        {"job_id": "a", "segment_index": 0, "quote": "ma attenzione", "level": "weak"}
    ]

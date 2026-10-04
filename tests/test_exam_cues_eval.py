from typing import Any

import pytest

from sbobina.exam_cues import CueLevel, ExamCue
from sbobina.exam_cues_eval import aggregate, compare_strong, ratio


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

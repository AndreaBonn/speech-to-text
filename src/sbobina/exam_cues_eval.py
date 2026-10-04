"""Pure aggregation for the exam cue evaluation (T013, V7).

Rows are decoded gold rows (see scripts/eval_exam_cues.py); nothing here reads
or writes files, so the script stays the only I/O shell.
"""

from collections import Counter
from typing import Any

from sbobina.exam_cues import ExamCue

LEVELS = ("strong", "weak")


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def precision_by_level(labeled: list[dict[str, Any]]) -> dict[str, Any]:
    precision = {}
    for level in LEVELS:
        predictions = [
            row
            for row in labeled
            if row["source"] == "detector" and row["predicted"] == level
        ]
        correct = sum(row["label"] == level for row in predictions)
        precision[level] = {
            "correct": correct,
            "total": len(predictions),
            "value": ratio(numerator=correct, denominator=len(predictions)),
        }
    return precision


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labeled = [row for row in rows if row["label"] != ""]
    positives = [row for row in labeled if row["label"] != "none"]
    detected = sum(row["source"] == "detector" for row in positives)
    return {
        "precision": precision_by_level(labeled=labeled),
        "wide_net_recall": {
            "estimate": True,
            "detected": detected,
            "missed": len(positives) - detected,
            "total": len(positives),
            "value": ratio(numerator=detected, denominator=len(positives)),
        },
        "counts": {
            "total": len(rows),
            "labeled": len(labeled),
            "unlabeled": len(rows) - len(labeled),
            "by_source": dict(Counter(row["source"] for row in rows)),
            "by_label": dict(Counter(row["label"] for row in rows)),
        },
    }


def compare_strong(
    cues_a: tuple[ExamCue, ...], cues_b: tuple[ExamCue, ...]
) -> dict[str, Any]:
    quotes_a = {
        " ".join(cue.quote.casefold().split())
        for cue in cues_a
        if cue.level == "strong"
    }
    quotes_b = {
        " ".join(cue.quote.casefold().split())
        for cue in cues_b
        if cue.level == "strong"
    }
    common = quotes_a & quotes_b
    return {
        "common": sorted(common),
        "common_count": len(common),
        "only_a": sorted(quotes_a - quotes_b),
        "only_b": sorted(quotes_b - quotes_a),
        "only_a_count": len(quotes_a - quotes_b),
        "only_b_count": len(quotes_b - quotes_a),
        "overlap": ratio(numerator=len(common), denominator=len(quotes_a | quotes_b)),
    }

"""Pure aggregation for the exam cue evaluation (T013, V7).

Rows are decoded gold rows (see scripts/eval_exam_cues.py); nothing here reads
or writes files, so the script stays the only I/O shell.
"""

from collections import Counter
from collections.abc import Mapping
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


def _cue_key(job_id: str, segment_index: int, quote: str) -> tuple[str, int, str]:
    return job_id, segment_index, " ".join(quote.casefold().split())


def _row_key(row: dict[str, Any]) -> tuple[str, int, str]:
    return _cue_key(
        job_id=row["job_id"], segment_index=row["segment_index"], quote=row["quote"]
    )


def _rescored(row: dict[str, Any], cue: ExamCue | None) -> dict[str, Any]:
    return {
        **row,
        "source": "detector" if cue else "wide_net",
        "predicted": cue.level if cue else None,
    }


def _unlabeled(
    fresh: dict[tuple[str, int, str], list[ExamCue]],
    seen: Counter[tuple[str, int, str]],
) -> list[dict[str, Any]]:
    # A cue repeated in one segment ("attenzione ... attenzione") counts once
    # per occurrence: those beyond the gold rows with that key are unlabeled.
    return [
        {
            "job_id": cue.job_id,
            "segment_index": cue.segment_index,
            "quote": cue.quote,
            "level": cue.level,
        }
        for key, found in fresh.items()
        for cue in found[seen[key] :]
    ]


def redetect(
    rows: list[dict[str, Any]], cues: Mapping[str, tuple[ExamCue, ...]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Score the current detector instead of the predictions stored at export.

    A gold row of a measured job becomes a detector row when a fresh cue has
    the same segment and quote, a wide-net row otherwise. Fresh cues with no
    gold row are returned apart: they have no label, so precision skips them.
    Rows of jobs not in cues are left as they are.
    """
    fresh: dict[tuple[str, int, str], list[ExamCue]] = {}
    for job_cues in cues.values():
        for cue in job_cues:
            key = _cue_key(
                job_id=cue.job_id, segment_index=cue.segment_index, quote=cue.quote
            )
            fresh.setdefault(key, []).append(cue)
    seen = Counter(_row_key(row=row) for row in rows if row["job_id"] in cues)
    scored = [
        _rescored(row=row, cue=fresh.get(_row_key(row=row), [None])[0])
        if row["job_id"] in cues
        else row
        for row in rows
    ]
    return scored, _unlabeled(fresh=fresh, seen=seen)

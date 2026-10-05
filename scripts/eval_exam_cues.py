"""Evaluate manually labeled JSONL without writing files (T013).

Empty labels are counted but excluded from precision and estimated wide-net
recall. A zero denominator yields null (n/d in text). Counts include every input
row, so pass each labeled candidate only once. --job-dirs reloads corrected
transcripts when available, otherwise originals; only find_exam_cues is timed,
once per job, without warm-up. The total is the sum of detector call times,
excluding loading and aggregation, not an end-to-end course API benchmark.
--duplicate-pair compares fresh strong cue sets, normalizing case and whitespace;
overlap is Jaccard (intersection / union), null when both sets are empty.
--redetect (needs --job-dirs) scores the current detector instead of the
predictions stored at export, so a pattern change shows up; fresh cues with no
gold row are listed apart, unlabeled.
"""

import argparse
import json
import logging
import math
import sys
import time
from pathlib import Path
from typing import Any

from sbobina.exam_cues import ExamCue, find_exam_cues
from sbobina.exam_cues_eval import (
    LEVELS,
    aggregate,
    compare_strong,
    redetect,
)
from sbobina.models import load_transcript

LABELS = (*LEVELS, "none", "")
PREFERRED_FILENAMES = ("audio.corretto.json", "audio.json")
MILLISECONDS_PER_SECOND = 1000
logger = logging.getLogger("sbobina.eval_exam_cues")


class GoldRowError(ValueError):
    """A gold row whose fields do not match the expected schema."""


def parse_row(text: str, location: str) -> dict[str, Any]:
    """Decode a gold row and reject invalid fields with their source location."""
    row = json.loads(s=text)
    if not isinstance(row, dict):
        raise GoldRowError(f"{location}: expected a JSON object")
    if row.get("label") not in LABELS:
        raise GoldRowError(f"{location}: invalid label {row.get('label')!r}")
    for field in ("job_id", "quote"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise GoldRowError(f"{location}: invalid {field}")
    source, predicted = row.get("source"), row.get("predicted")
    if not (
        (source == "detector" and predicted in LEVELS)
        or (source == "wide_net" and "predicted" in row and predicted is None)
    ):
        raise GoldRowError(f"{location}: inconsistent source/predicted")
    index, start = row.get("segment_index"), row.get("start")
    if type(index) is not int or index < 0:
        raise GoldRowError(f"{location}: invalid segment_index")
    if isinstance(start, bool) or not isinstance(start, (int, float)):
        raise GoldRowError(f"{location}: invalid start")
    if not math.isfinite(start) or start < 0:
        raise GoldRowError(f"{location}: invalid start")
    return row


def measure_jobs(
    directories: list[Path],
) -> tuple[dict[str, float], dict[str, tuple[ExamCue, ...]]]:
    timings: dict[str, float] = {}
    cues = {}
    for directory in directories:
        if directory.name in timings:
            raise ValueError(f"Duplicate job_id: {directory.name}")
        path = next(
            (
                directory / name
                for name in PREFERRED_FILENAMES
                if (directory / name).is_file()
            ),
            None,
        )
        if path is None:
            raise ValueError(f"No transcript in {directory}")
        transcript = load_transcript(path=path)
        started = time.perf_counter()
        found = find_exam_cues(transcript=transcript, job_id=directory.name)
        elapsed = time.perf_counter() - started
        timings[directory.name] = elapsed * MILLISECONDS_PER_SECOND
        cues[directory.name] = found
    return timings, cues


def build_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    report = aggregate(rows=rows)
    report["by_job"] = {
        job: aggregate(rows=[row for row in rows if row["job_id"] == job])
        for job in sorted({row["job_id"] for row in rows})
    }
    count = report["counts"]["unlabeled"]
    report["warnings"] = (
        [f"{count} righe non etichettate escluse dalle metriche."] if count else []
    )
    return report


def runtime_report(
    directories: list[Path], pair: list[str] | None
) -> tuple[dict[str, Any], dict[str, tuple[ExamCue, ...]]]:
    if pair and (
        pair[0] == pair[1] or not set(pair) <= {path.name for path in directories}
    ):
        raise ValueError(
            "--duplicate-pair requires two distinct jobs supplied via --job-dirs"
        )
    timings, cues = measure_jobs(directories=directories)
    latency = {
        "status": "measured" if directories else "skipped",
        "by_job_ms": timings,
        "total_ms": sum(timings.values()) if timings else None,
        "scope": "find_exam_cues only; one call per job, no warm-up",
    }
    stability = None
    if pair:
        stability = dict(
            job_a=pair[0],
            job_b=pair[1],
            **compare_strong(cues_a=cues[pair[0]], cues_b=cues[pair[1]]),
        )
    return {"latency": latency, "stability": stability}, cues


def format_metric(metric: dict[str, Any], numerator: str) -> str:
    value = "n/d" if metric["value"] is None else f"{metric['value']:.4f}"
    return f"{value} ({metric[numerator]}/{metric['total']})"


def format_metrics(report: dict[str, Any]) -> list[str]:
    counts = report["counts"]
    lines = [
        f"Righe: {counts['total']}; etichettate: {counts['labeled']}; non etichettate: {counts['unlabeled']}",
        f"Per fonte: {json.dumps(counts['by_source'], ensure_ascii=False)}",
        f"Per etichetta: {json.dumps(counts['by_label'], ensure_ascii=False)}",
    ]
    lines.extend(
        f"Precisione {level}: {format_metric(metric=report['precision'][level], numerator='correct')}"
        for level in LEVELS
    )
    lines.append(
        f"Recall stimato sulla rete larga: {format_metric(metric=report['wide_net_recall'], numerator='detected')}"
    )
    lines.append(
        f"Segnali persi nella rete larga: {report['wide_net_recall']['missed']}"
    )
    return lines


def format_latency(latency: dict[str, Any]) -> list[str]:
    lines = []
    if latency["status"] == "skipped":
        lines.append("Latenza: non misurata (nessuna --job-dirs).")
    else:
        lines.append(
            "Latenza: sola chiamata find_exam_cues, una misura per lezione senza riscaldamento."
        )
        lines.extend(
            f"  {job}: {value:.3f} ms" for job, value in latency["by_job_ms"].items()
        )
        lines.append(f"  Totale: {latency['total_ms']:.3f} ms")
    return lines


def format_stability(stability: dict[str, Any] | None) -> list[str]:
    lines = []
    if stability is None:
        lines.append("Stabilità: non richiesta.")
    else:
        overlap = (
            "n/d" if stability["overlap"] is None else f"{stability['overlap']:.2%}"
        )
        lines.append(
            f"Stabilità {stability['job_a']} / {stability['job_b']}: sovrapposizione Jaccard {overlap}"
        )
        for field in ("common", "only_a", "only_b"):
            lines.append(
                f"  {field} ({len(stability[field])}): {json.dumps(stability[field], ensure_ascii=False)}"
            )
    return lines


def format_unlabeled(report: dict[str, Any]) -> list[str]:
    if "unlabeled_detections" not in report:
        return []
    found = report["unlabeled_detections"]
    return [
        f"Rilevamenti senza etichetta ({len(found)}): "
        + json.dumps([item["quote"] for item in found], ensure_ascii=False)
    ]


def format_report(report: dict[str, Any]) -> str:
    lines = format_metrics(report=report)
    lines.extend(format_unlabeled(report=report))
    lines.append("La rete larga non è esaustiva: il recall è soltanto una stima.")
    for job, metrics in report["by_job"].items():
        lines.append(f"Lezione {job}:")
        lines.extend(f"  {line}" for line in format_metrics(report=metrics))
    lines.extend(format_latency(latency=report["latency"]))
    lines.extend(format_stability(stability=report["stability"]))
    lines.extend(report["warnings"])
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gold_files", type=Path, nargs="+")
    parser.add_argument("--job-dirs", type=Path, nargs="+", default=[])
    parser.add_argument("--duplicate-pair", nargs=2, metavar=("JOB_A", "JOB_B"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--redetect", action="store_true")
    return parser.parse_args(args=argv)


def evaluate(args: argparse.Namespace, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if args.redetect and not args.job_dirs:
        raise ValueError("--redetect requires --job-dirs")
    runtime, cues = runtime_report(directories=args.job_dirs, pair=args.duplicate_pair)
    unlabeled = None
    if args.redetect:
        rows, unlabeled = redetect(rows=rows, cues=cues)
    report = build_report(rows=rows)
    report.update(runtime)
    if unlabeled is not None:
        report["unlabeled_detections"] = unlabeled
    return report


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv=argv)
    rows = []
    location = "input"
    try:
        for path in args.gold_files:
            location = str(path)
            with path.open(encoding="utf-8") as stream:
                for number, text in enumerate(stream, start=1):
                    location = f"{path}:{number}"
                    rows.append(parse_row(text=text, location=location))
        location = "job directories"
        report = evaluate(args=args, rows=rows)
        for warning in report["warnings"]:
            logger.warning("%s", warning)
        output = (
            json.dumps(report, ensure_ascii=False, allow_nan=False) + "\n"
            if args.json
            else format_report(report=report)
        )
        sys.stdout.write(output)
    except (OSError, ValueError, KeyError, TypeError) as error:
        logger.error("Evaluation failed at %s: %s", location, error)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

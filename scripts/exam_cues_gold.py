"""Export exam cue candidates for manual labeling (T013).

Run with job directories and optional --output-dir (default: data/eval).
Each label starts empty; accepted completed labels are "strong", "weak", "none".
Files are named exam-cues-gold-<Unix timestamp in nanoseconds>.jsonl. Exclusive
creation preserves previous runs, including in the event of a timestamp collision.
Corrected transcripts take precedence over originals. Detector candidates precede
wide-net candidates; normalized duplicates keep their first detector occurrence.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from time import time_ns
from typing import Any

from sbobina.exam_cues import SENTENCE_SEPARATOR, find_exam_cues
from sbobina.models import Transcript, load_transcript

logger = logging.getLogger("sbobina.exam_cues_gold")

PREFERRED_FILENAMES = ("audio.corretto.json", "audio.json")
WIDE_NET_KEYWORDS = (
    "esame",
    "chieder",
    "ricorda",
    "importante",
    "fondamentale",
    "attenzione",
    "domanda",
)


def normalize_quote(quote: str) -> str:
    return " ".join(quote.casefold().split())


def wide_candidates(transcript: Transcript, job_id: str) -> list[dict[str, Any]]:
    rows = []
    for segment_index, segment in enumerate(transcript.segments):
        for sentence in SENTENCE_SEPARATOR.split(string=segment.text):
            quote = sentence.strip()
            if not any(keyword in quote.casefold() for keyword in WIDE_NET_KEYWORDS):
                continue
            rows.append(
                {
                    "job_id": job_id,
                    "segment_index": segment_index,
                    "start": segment.start,
                    "quote": quote,
                    "predicted": None,
                    "source": "wide_net",
                    "label": "",
                }
            )
    return rows


def collect_candidates(transcript: Transcript, job_id: str) -> list[dict[str, Any]]:
    """Select detector and lexical candidates, deduplicated within one job."""
    detector = [
        {
            "job_id": cue.job_id,
            "segment_index": cue.segment_index,
            "start": cue.start,
            "quote": cue.quote,
            "predicted": cue.level,
            "source": "detector",
            "label": "",
        }
        for cue in find_exam_cues(transcript=transcript, job_id=job_id)
    ]
    candidates: dict[str, dict[str, Any]] = {}
    for row in detector + wide_candidates(transcript=transcript, job_id=job_id):
        candidates.setdefault(normalize_quote(quote=row["quote"]), row)
    return list(candidates.values())


def validate_job_ids(directories: list[Path]) -> None:
    names = [directory.name for directory in directories]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate job_id in job directories")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_dirs", type=Path, nargs="+")
    parser.add_argument("--output-dir", type=Path, default=Path("data/eval"))
    args = parser.parse_args(args=argv)
    rows = []
    try:
        validate_job_ids(directories=args.job_dirs)
        for directory in args.job_dirs:
            paths = [directory / name for name in PREFERRED_FILENAMES]
            path = next((path for path in paths if path.is_file()), None)
            if path is None:
                raise ValueError(f"No transcript in {directory}")
            transcript = load_transcript(path=path)
            rows.extend(collect_candidates(transcript, job_id=directory.name))
        args.output_dir.mkdir(parents=True, exist_ok=True)
        output = args.output_dir / f"exam-cues-gold-{time_ns()}.jsonl"
        with output.open(mode="x", encoding="utf-8") as stream:
            stream.writelines(
                json.dumps(row, ensure_ascii=False) + "\n" for row in rows
            )
        sys.stdout.write(f"{output}\n")
    except (OSError, ValueError, KeyError, TypeError) as error:
        logger.error("Gold export failed: %s", error)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

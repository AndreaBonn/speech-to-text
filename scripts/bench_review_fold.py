"""Benchmark the review fold (V3) and one reviews.jsonl append under load (T031).

    uv run python scripts/bench_review_fold.py [--cards N] [--reviews N] [--runs N] [--json]

Generates a synthetic deck directly as JSONL via card_models.dump_card_event /
dump_review, bypassing card_store.create_card and record_review: looping the
public API to write thousands of cards and tens of thousands of reviews would
itself pay the O(n^2) fold-before-append cost this benchmark exists to
measure, dominating setup time instead of the numbers we want.

Measures, over --runs repetitions:
  (a) card_store.load_cards -- the full fold of cards.jsonl + reviews.jsonl.
  (b) card_store._append_record on reviews.jsonl at --reviews lines -- the
      cost the ADR names ("_append_record rilegge l'intero file per
      controllare l'ultima riga"), called directly rather than through
      record_review so the fold already measured in (a) is not counted a
      second time into the append number.

Everything lives under a TemporaryDirectory removed on exit; nothing is
written outside it.
"""

import argparse
import json
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from sbobina.card_models import (
    CardCreated,
    LectureAnchor,
    ReviewEvent,
    dump_card_event,
    dump_review,
    load_review,
)
from sbobina.flashcard_scheduler import FsrsState, FsrsStateLabel, Rating
from sbobina.web.card_store import _append_record, cards_path, load_cards, reviews_path

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)
BENCH_JOB_ID = str(uuid4())
DEFAULT_CARDS = 3000
DEFAULT_REVIEWS = 30000
DEFAULT_RUNS = 10
APPEND_SAMPLE_PREFIX = "bench-append"
COURSE_ID = "bench"


def _card_event(index: int) -> CardCreated:
    anchor = LectureAnchor(
        job_id=BENCH_JOB_ID,
        revision="r1",
        segment_index=index,
        quote=f"quote {index}",
    )
    return CardCreated(
        card_id=f"card-{index}",
        occurred_at=BASE_TIME,
        front=f"front {index}",
        back=f"back {index}",
        source="bench",
        anchor=anchor,
    )


def _review_event(card_id: str, index: int) -> ReviewEvent:
    reviewed_at = BASE_TIME + timedelta(minutes=index)
    fsrs = FsrsState(
        state=FsrsStateLabel.REVIEW,
        step=None,
        stability=1.0,
        difficulty=5.0,
        due=reviewed_at + timedelta(days=1),
    )
    return ReviewEvent(
        card_id=card_id,
        rating=Rating.GOOD,
        reviewed_at=reviewed_at,
        duration_ms=None,
        fsrs=fsrs,
    )


def generate_deck(
    cards_file: Path, reviews_file: Path, num_cards: int, num_reviews: int
) -> None:
    """Write num_cards CardCreated and num_reviews ReviewEvent lines directly."""
    cards_file.parent.mkdir(parents=True, exist_ok=True)
    with cards_file.open("w", encoding="utf-8") as handle:
        for index in range(num_cards):
            handle.write(dump_card_event(event=_card_event(index=index)))
    with reviews_file.open("w", encoding="utf-8") as handle:
        for index in range(num_reviews):
            card_id = f"card-{index % num_cards}"
            handle.write(dump_review(event=_review_event(card_id=card_id, index=index)))


def _time_ms(action: Callable[[], None]) -> float:
    start = time.perf_counter()
    action()
    return (time.perf_counter() - start) * 1000.0


def measure_fold(courses_dir: Path, course_id: str, runs: int) -> list[float]:
    def _load() -> None:
        load_cards(courses_dir=courses_dir, course_id=course_id)

    return [_time_ms(action=_load) for _ in range(runs)]


def measure_append(reviews_file: Path, runs: int) -> list[float]:
    timings: list[float] = []
    for index in range(runs):
        event = _review_event(card_id=f"{APPEND_SAMPLE_PREFIX}-{index}", index=index)
        content = dump_review(event=event)

        def _append(content: str = content) -> None:
            _append_record(path=reviews_file, content=content, parse=load_review)

        timings.append(_time_ms(action=_append))
    return timings


def summarize(values: list[float]) -> dict[str, float]:
    return {
        "p50_ms": round(statistics.median(values), 3),
        "max_ms": round(max(values), 3),
    }


@dataclass(frozen=True, kw_only=True)
class BenchResult:
    runs: int
    fold: dict[str, float]
    append: dict[str, float]


def run_benchmark(num_cards: int, num_reviews: int, runs: int) -> BenchResult:
    with TemporaryDirectory(prefix="bench-review-fold-") as raw_tmp_dir:
        courses_dir = Path(raw_tmp_dir)
        cards_file = cards_path(courses_dir=courses_dir, course_id=COURSE_ID)
        reviews_file = reviews_path(courses_dir=courses_dir, course_id=COURSE_ID)
        generate_deck(
            cards_file=cards_file,
            reviews_file=reviews_file,
            num_cards=num_cards,
            num_reviews=num_reviews,
        )
        fold_timings = measure_fold(
            courses_dir=courses_dir, course_id=COURSE_ID, runs=runs
        )
        append_timings = measure_append(reviews_file=reviews_file, runs=runs)
    return BenchResult(
        runs=runs, fold=summarize(fold_timings), append=summarize(append_timings)
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cards", type=int, default=DEFAULT_CARDS)
    parser.add_argument("--reviews", type=int, default=DEFAULT_REVIEWS)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _print_report(result: BenchResult, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                {"runs": result.runs, "fold": result.fold, "append": result.append}
            )
        )
        return
    print(f"runs: {result.runs}")
    print(
        f"fold (load_cards):    p50={result.fold['p50_ms']} ms  max={result.fold['max_ms']} ms"
    )
    print(
        f"append (reviews.jsonl): p50={result.append['p50_ms']} ms  max={result.append['max_ms']} ms"
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    result = run_benchmark(
        num_cards=args.cards, num_reviews=args.reviews, runs=args.runs
    )
    _print_report(result=result, as_json=args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

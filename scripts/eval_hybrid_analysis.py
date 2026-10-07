"""Offline analyses over saved eval_hybrid outputs (specs/004-hybrid-retrieval, T016).

Reproduces two tables of eval.md without new embeddings:

    uv run python scripts/eval_hybrid_analysis.py sweep \\
        --dense out/x8b-dense.json --judgments data/eval/retrieval-hybrid/judging
    uv run python scripts/eval_hybrid_analysis.py weighted \\
        --bm25 out/x8b-bm25.json --dense out/x8b-dense.json --weight 2 \\
        --judgments data/eval/retrieval-hybrid/judging

Both read the saved top_k only, so the inputs must come from runs with
``--k 50`` (the production candidate limit) for the numbers to hold.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from eval_hybrid_io import apply_judgments, load_verdicts, print_summary

from sbobina.hybrid_eval import gold_ref
from sbobina.rank_fusion import RRF_K
from sbobina.retrieval_metrics import RankedPassage, first_judged_rank

DEFAULT_GOLD = Path("data/eval/retrieval-hybrid/gold.json")
HIT_CUTOFF = 8
SWEEP_FLOORS = (0.0, 0.35, 0.40, 0.44, 0.45, 0.46, 0.465, 0.48, 0.50)
NEGATIVE = "negative"


def load_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))[
        "records"
    ]
    return records


def load_gold_by_id(path: Path) -> dict[str, dict[str, Any]]:
    items = json.loads(path.read_text(encoding="utf-8"))["items"]
    return {item["id"]: item for item in items}


def hit_with_floor(
    record: dict[str, Any], item: dict[str, Any], votes: dict[str, int], floor: float
) -> bool:
    """hit@8 once passages under the cosine floor are dropped before the cut."""
    kept = [entry for entry in record["top_k"] if entry["cosine"] >= floor]
    ranked = [
        RankedPassage(passage_id=entry["passage_id"], ref=gold_ref(entry["ref"]))
        for entry in kept[:HIT_CUTOFF]
    ]
    gold = [gold_ref(raw) for raw in item["references"]]
    return first_judged_rank(ranked=ranked, gold_refs=gold, votes=votes) is not None


def negatives_above(
    records: Sequence[dict[str, Any]], gold: dict[str, dict[str, Any]], floor: float
) -> tuple[int, int]:
    """Passages in the top-8 of `negative` questions above the floor, and questions hit."""
    tops = [
        r["top_k"][:HIT_CUTOFF] for r in records if gold[r["id"]]["type"] == NEGATIVE
    ]
    passages = sum(1 for top in tops for entry in top if entry["cosine"] >= floor)
    questions = sum(1 for top in tops if top and top[0]["cosine"] >= floor)
    return passages, questions


def run_sweep(args: argparse.Namespace) -> int:
    gold = load_gold_by_id(path=args.gold)
    votes = load_verdicts(judging_dir=args.judgments)
    records = load_records(path=args.dense)
    answerable = [r for r in records if gold[r["id"]]["type"] != NEGATIVE]
    print(f"floor  hit@8/{len(answerable)}  negative_passages  negative_questions")
    for floor in SWEEP_FLOORS:
        hits = sum(
            hit_with_floor(
                record=r, item=gold[r["id"]], votes=votes.get(r["id"], {}), floor=floor
            )
            for r in answerable
        )
        passages, questions = negatives_above(records=records, gold=gold, floor=floor)
        print(f"{floor:<6} {hits:>4}       {passages:>4}               {questions}")
    return 0


def weighted_top_k(
    bm25_top: Sequence[dict[str, Any]],
    dense_top: Sequence[dict[str, Any]],
    weight: float,
) -> list[dict[str, Any]]:
    """Two-list reciprocal rank fusion with `weight` on the dense list."""
    scores: dict[str, float] = {}
    entries: dict[str, dict[str, Any]] = {}
    for list_weight, top in ((1.0, bm25_top), (weight, dense_top)):
        for entry in top:
            pid = entry["passage_id"]
            scores[pid] = scores.get(pid, 0.0) + list_weight / (RRF_K + entry["rank"])
            entries[pid] = entry
    order = sorted(scores, key=lambda pid: -scores[pid])
    return [{**entries[pid], "rank": i} for i, pid in enumerate(order, start=1)]


def run_weighted(args: argparse.Namespace) -> int:
    gold = load_gold_by_id(path=args.gold)
    bm25 = {r["id"]: r for r in load_records(path=args.bm25)}
    fused = [
        {
            **r,
            "top_k": weighted_top_k(
                bm25_top=bm25[r["id"]]["top_k"],
                dense_top=r["top_k"],
                weight=args.weight,
            ),
        }
        for r in load_records(path=args.dense)
    ]
    judged = apply_judgments(
        records=fused, gold_by_id=gold, votes=load_verdicts(judging_dir=args.judgments)
    )
    print_summary(records=judged)
    return 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("sweep", "weighted"):
        command = sub.add_parser(name)
        command.add_argument("--dense", type=Path, required=True)
        command.add_argument("--judgments", type=Path, required=True)
        command.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
        if name == "weighted":
            command.add_argument("--bm25", type=Path, required=True)
            command.add_argument("--weight", type=float, default=2.0)
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args(sys.argv[1:])
    if args.command == "sweep":
        return run_sweep(args=args)
    return run_weighted(args=args)


if __name__ == "__main__":
    sys.exit(main())

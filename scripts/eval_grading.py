"""V6 again with multi-point solutions: does the judge mark half answers partial? (A31)

Measurement script, not part of the suite. It needs Ollama with the judge
model and a dataset of questions and labelled answers:

    uv run python scripts/eval_grading.py data/eval/grading/dataset-v7.json

The dataset is a JSON list of questions, each with "format" ("open"/"oral"),
"question", "solution" and "answers": [{"text", "expected", "kind"}], where
"expected" is corretta/parziale/errata and "kind" says how the answer was
written (full, half, error, wrong). Every answer is graded RUNS times through
grading.grade, the same call the server makes; results are printed and saved
next to the dataset as <name>-results.json.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import TypedDict

from ollama import Client

from sbobina.generation_models import GenerationFormat, GenerationQuestion
from sbobina.grading import GradingRequest, grade
from sbobina.ollama_chat import chat_json
from sbobina.settings import Settings

RUNS = 3
UNGRADED = "nessun giudizio"


class Answer(TypedDict):
    text: str
    expected: str
    kind: str


class Question(TypedDict):
    format: str
    question: str
    solution: str
    answers: list[Answer]


def grade_answer(
    question: Question, answer: Answer, client: Client
) -> tuple[str, float]:
    """The judge's outcome for one answer and the seconds it took."""
    request = GradingRequest(
        question=GenerationQuestion(
            question=question["question"],
            options=(),
            correct_index=None,
            solution=question["solution"],
            citations=(),
        ),
        format=GenerationFormat(question["format"]),
        answer=answer["text"],
    )
    started = time.perf_counter()
    result = grade(
        request=request,
        chat=lambda chat_request: chat_json(client=client, request=chat_request),
        model=Settings().ollama_model,
    )
    elapsed = time.perf_counter() - started
    outcome = result.judgement.outcome.value if result.judgement else UNGRADED
    return outcome, elapsed


def run_all(dataset: list[Question]) -> list[dict[str, object]]:
    client = Client(host=Settings().ollama_host)
    rows = []
    for run in range(1, RUNS + 1):
        for index, question in enumerate(dataset):
            for answer in question["answers"]:
                outcome, seconds = grade_answer(
                    question=question, answer=answer, client=client
                )
                rows.append(
                    {
                        "run": run,
                        "question": index,
                        "kind": answer["kind"],
                        "expected": answer["expected"],
                        "outcome": outcome,
                        "seconds": seconds,
                    }
                )
        print(f"esecuzione {run} di {RUNS} finita", flush=True)
    return rows


def summarize(rows: list[dict[str, object]]) -> None:
    for run in range(1, RUNS + 1):
        mine = [r for r in rows if r["run"] == run]
        agree = sum(r["outcome"] == r["expected"] for r in mine)
        print(f"esecuzione {run}: accordo {agree}/{len(mine)}")
    by_kind: dict[str, Counter[str]] = {}
    for row in rows:
        by_kind.setdefault(str(row["kind"]), Counter())[str(row["outcome"])] += 1
    for kind, counts in sorted(by_kind.items()):
        print(f"{kind}: {dict(counts)}")


def main() -> int:
    path = Path(sys.argv[1])
    dataset = json.loads(path.read_text(encoding="utf-8"))
    rows = run_all(dataset=dataset)
    path.with_name(f"{path.stem}-results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summarize(rows=rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""V9 on real course pages: citations of generations from the OCR of eval_math_real.

Measurement script, not part of the suite. It needs Ollama with the
generation model and data/eval/math-real/pages.jsonl from eval_math_real.py:

    uv run python scripts/eval_citations_real.py

Same procedure as eval_citations_math.py (one open exam of 3 questions and
one summary per page, the page first and the others cut to budget, every
proposed citation resolved again), with the OCR text of the real slides as
material and the first line of each slide's text layer as topic. Each
generation is appended to data/eval/math-real/citations-runs.jsonl as it ends
and skipped on a rerun.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

from eval_citations_math import (
    FORMATS,
    KEPT,
    Run,
    ranked_for,
    rate,
    run_one,
    summarize,
)

from sbobina.retrieval import DocumentSource, RetrievedPassage

DATA = Path("data/eval/math-real")
DOC_ID = "lezioni-11"
RUNS_FILE = DATA / "citations-runs.jsonl"


def load_pages() -> list[dict[str, object]]:
    lines = (DATA / "pages.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def passages_of(pages: list[dict[str, object]]) -> list[RetrievedPassage]:
    """One passage per page, as chunk_document_pages makes for a short page."""
    return [
        RetrievedPassage(
            text=str(page["ocr"]),
            source=DocumentSource(doc_id=DOC_ID, page=int(str(page["page"])), chunk=0),
            passage_id=f"{DOC_ID}:p{page['page']}:c0",
        )
        for page in pages
    ]


def topic_of(page: dict[str, object]) -> str:
    """The slide title: the first non-empty line of the text layer."""
    lines = (line.strip(" \r") for line in str(page["reference"]).splitlines())
    return next((line for line in lines if line), "")


def load_done() -> list[Run]:
    """Generations already measured by an earlier, interrupted run."""
    if not RUNS_FILE.exists():
        return []
    runs = []
    for line in RUNS_FILE.read_text(encoding="utf-8").splitlines():
        data = json.loads(line)
        data["citations"] = [tuple(pair) for pair in data["citations"]]
        runs.append(Run(**data))
    return runs


def collect_runs() -> list[Run]:
    pages = load_pages()
    passages = passages_of(pages=pages)
    topics = [topic_of(page=page) for page in pages]
    if len(set(topics)) < len(topics):
        # The resume key is (topic, format): equal titles would mix two pages.
        raise SystemExit(f"titoli di slide ripetuti: {topics}")
    runs = load_done()
    done = {(run.topic, run.format) for run in runs}
    for page in pages:
        ranked = ranked_for(page=int(str(page["page"])), passages=passages)
        topic = topic_of(page=page)
        for format_ in FORMATS:
            if (topic, format_.value) in done:
                continue
            run = run_one(topic=topic, format_=format_, ranked=ranked)
            with RUNS_FILE.open("a", encoding="utf-8") as out:
                out.write(json.dumps(asdict(run), ensure_ascii=False) + "\n")
            print(f"pagina {page['page']} {format_.value}: {run.outcome}", flush=True)
            runs.append(run)
    return runs


def main() -> int:
    runs = collect_runs()
    tally = summarize(runs=runs)
    total = tally.formula + tally.plain
    (DATA / "citations.json").write_text(
        json.dumps([asdict(run) for run in runs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"con formula: {rate(tally.formula)} {dict(tally.formula)}")
    print(f"senza formula: {rate(tally.plain)} {dict(tally.plain)}")
    print(f"totale: {rate(total)}, tenute {total[KEPT]}")
    print(
        f"testi: {sum(r.texts for r in runs)}, con formula fra delimitatori "
        f"{sum(r.texts_with_formula for r in runs)}, con barre doppie "
        f"{sum(r.texts_double_backslash for r in runs)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""V9 on real course pages: citations of generations from the OCR of eval_math_real.

Measurement script, not part of the suite. It needs Ollama with the
generation model and data/eval/math-real/pages.jsonl from eval_math_real.py:

    uv run python scripts/eval_citations_real.py

Same procedure as eval_citations_math.py (one open exam of 3 questions and
one summary per page, the page first and the others cut to budget, every
proposed citation resolved again), with the OCR text of the real slides as
material and the first line of each slide's text layer as topic. Each
generation is appended to data/eval/math-real/citations-runs.jsonl as it ends
and skipped on a rerun. The stored OCR text goes through the current OCR
cleanup again, so the measure follows the shipped code.

Between generations it pauses PAUSE_S seconds and then waits, up to
COOL_WAIT_S, for the GPU to drop to COOL_GPU_C: this laptop shut down twice
under back-to-back generations (2026-10-06). It rests at about 70 C.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
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

from sbobina.document_models import DocumentStatus
from sbobina.extracted_text import ExtractedText, Page
from sbobina.ocr_pipeline import ocr_missing_pages
from sbobina.retrieval import DocumentSource, RetrievedPassage

DATA = Path("data/eval/math-real")
DOC_ID = "lezioni-11"
RUNS_FILE = DATA / "citations-runs.jsonl"
PAUSE_S = 60
COOL_GPU_C = 75
COOL_WAIT_S = 300
POLL_S = 10


def load_pages() -> list[dict[str, object]]:
    lines = (DATA / "pages.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def passages_of(pages: list[dict[str, object]]) -> list[RetrievedPassage]:
    """One passage per page, as chunk_document_pages makes for a short page."""
    return [
        RetrievedPassage(
            text=cleaned_ocr(text=str(page["ocr"])),
            source=DocumentSource(doc_id=DOC_ID, page=int(str(page["page"])), chunk=0),
            passage_id=f"{DOC_ID}:p{page['page']}:c0",
        )
        for page in pages
    ]


def cleaned_ocr(text: str) -> str:
    """The stored OCR text as the current OCR cleanup would store it."""
    extracted = ocr_missing_pages(
        extracted=ExtractedText(
            pages=(Page(text="", no_text=True),),
            status=DocumentStatus.READY_NO_TEXT,
            encoding=None,
        ),
        read_page=lambda _: text,
        on_progress=lambda done, total: None,
        prompt_version="ocr-v2",
    )
    return extracted.pages[0].text


def gpu_temperature() -> int:
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(out.stdout.split()[0])


def cool_down() -> None:
    """Pause, then wait for the GPU to cool, giving up after COOL_WAIT_S."""
    time.sleep(PAUSE_S)
    deadline = time.monotonic() + COOL_WAIT_S
    while (temp := gpu_temperature()) > COOL_GPU_C:
        if time.monotonic() > deadline:
            print(f"GPU ancora a {temp} C, riparto comunque", flush=True)
            return
        time.sleep(POLL_S)


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
            cool_down()
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

"""V9: citations dropped by real generations on formula pages (T068).

Measurement script, not part of the suite. It needs Ollama with the generation
model and the OCR output of eval_math.py (data/eval/math/ocr-ocr-v2.json):

    uv run python scripts/eval_citations_math.py

For each of the ten V10 pages it runs one open exam (3 questions) and one
summary on that page's topic, through the app's own path: page text as the
OCR stored it, chunk_document_pages, the page first and the others after it
cut to the format's word budget, generation_pipeline.generate with the real
model. Every proposed citation is then resolved again, so the rate counts
citations, not the items the pipeline keeps or drops. Each generation is
appended to data/eval/math/citations-runs.jsonl as it ends and skipped on a
rerun, so an interrupted measurement resumes; the totals go to
data/eval/math/citations.json.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ollama import Client
from pydantic import BaseModel, ValidationError

from sbobina.document_passages import chunk_document_pages
from sbobina.extracted_text import Page
from sbobina.generation_models import (
    GenerationFormat,
    GenerationRequest,
    ProposedCitation,
    SummaryResponse,
    TextQuestionResponse,
)
from sbobina.generation_pipeline import (
    GenerationOptions,
    GenerationResult,
    generate,
)
from sbobina.ollama_chat import ChatRequest, chat_json, strip_markdown_fence
from sbobina.retrieval import DocumentSource, RetrievedPassage, cut_to_budget
from sbobina.settings import Settings
from sbobina.source_citations import (
    ProposedSourceCitation,
    SourceRejection,
    resolve_citation,
)
from sbobina.web.generation_runner import compute_budget_words, compute_options

DATA = Path("data/eval/math")
DOC_ID = "eval-math"
QUESTION_COUNT = 3
DROP_THRESHOLD = 0.20
DELIMITER = re.compile(r"\\\(|\\\[")
# Two literal backslashes before a letter: the model escaped twice (T069).
DOUBLE_BACKSLASH = re.compile(r"\\\\[A-Za-z]")
FORMATS = (GenerationFormat.OPEN, GenerationFormat.SUMMARY)
KEPT = "KEPT"
RUNS_FILE = DATA / "citations-runs.jsonl"


@dataclass(frozen=True)
class Run:
    topic: str
    format: str
    outcome: str
    attempts: int
    items_kept: int
    items_discarded: dict[str, int]
    # (quote, outcome) for every citation the model proposed.
    citations: list[tuple[str, str]]
    # Generated texts (questions, solutions, summary sentences): how many
    # carry a delimited formula, how many a doubly escaped command.
    texts: int = 0
    texts_with_formula: int = 0
    texts_double_backslash: int = 0


@dataclass
class Tally:
    """Citation outcomes, split by whether the quote holds a formula."""

    formula: Counter[str] = field(default_factory=Counter)
    plain: Counter[str] = field(default_factory=Counter)

    def add(self, quote: str, outcome: str) -> None:
        has_formula = "\\(" in quote or "\\[" in quote
        (self.formula if has_formula else self.plain)[outcome] += 1


def load_passages() -> list[RetrievedPassage]:
    ocr = json.loads((DATA / "ocr-ocr-v2.json").read_text(encoding="utf-8"))
    pages = tuple(
        Page(text=page["text"], no_text=False, ocr=True, ocr_prompt="ocr-v2")
        for page in ocr["pages"]
    )
    return [
        RetrievedPassage(
            text=chunk.text,
            source=DocumentSource(doc_id=DOC_ID, page=chunk.page, chunk=chunk.chunk),
            passage_id=chunk.passage_id,
        )
        for chunk in chunk_document_pages(doc_id=DOC_ID, pages=pages)
    ]


def ranked_for(page: int, passages: list[RetrievedPassage]) -> list[RetrievedPassage]:
    """The topic's page first, as retrieval would rank it, then the others."""

    def on_page(passage: RetrievedPassage) -> bool:
        source = passage.source
        return isinstance(source, DocumentSource) and source.page == page

    first = [p for p in passages if on_page(passage=p)]
    return first + [p for p in passages if not on_page(passage=p)]


def proposed_citations(raw: str, format_: GenerationFormat) -> list[ProposedCitation]:
    schema: type[BaseModel] = (
        SummaryResponse if format_ is GenerationFormat.SUMMARY else TextQuestionResponse
    )
    try:
        reply = schema.model_validate_json(strip_markdown_fence(content=raw))
    except ValidationError:
        return []
    if isinstance(reply, SummaryResponse):
        return [c for s in reply.sections for f in s.sentences for c in f.citations]
    assert isinstance(reply, TextQuestionResponse)
    return [c for q in reply.questions for c in q.citations]


def build_inputs(
    topic: str, format_: GenerationFormat, ranked: list[RetrievedPassage]
) -> tuple[GenerationRequest, list[RetrievedPassage], GenerationOptions]:
    """Request, budgeted passages and options, as the generation runner sets them."""
    count = 1 if format_ is GenerationFormat.SUMMARY else QUESTION_COUNT
    options = compute_options(
        count=count, format_=format_, model=Settings().ollama_model
    )
    passages = cut_to_budget(
        ranked=ranked,
        budget_words=compute_budget_words(format_=format_, options=options),
    )
    request = GenerationRequest.model_validate(
        {"format": format_.value, "count": count, "topic": topic}
    )
    return request, passages, options


def resolve_all(
    raw: str, format_: GenerationFormat, passages: list[RetrievedPassage]
) -> list[tuple[str, str]]:
    """(quote, outcome) for every citation the model proposed in its reply."""
    citations = []
    for proposed in proposed_citations(raw=raw, format_=format_):
        resolved = resolve_citation(
            passages=passages,
            citation=ProposedSourceCitation(
                label=proposed.passage, quote=proposed.quote
            ),
        )
        outcome = resolved.reason if isinstance(resolved, SourceRejection) else KEPT
        citations.append((proposed.quote, str(outcome)))
    return citations


def run_one(
    topic: str, format_: GenerationFormat, ranked: list[RetrievedPassage]
) -> Run:
    client = Client(host=Settings().ollama_host)
    replies: list[str] = []

    def chat(request: ChatRequest) -> str:
        replies.append(chat_json(client=client, request=request))
        return replies[-1]

    request, passages, options = build_inputs(
        topic=topic, format_=format_, ranked=ranked
    )
    result = generate(request=request, passages=passages, chat=chat, options=options)
    return Run(
        topic=topic,
        format=format_.value,
        outcome=result.outcome.value,
        attempts=len(replies),
        items_kept=len(result.questions)
        + sum(len(s.sentences) for s in result.sections),
        items_discarded={d.reason: d.count for d in result.discarded},
        citations=resolve_all(raw=replies[-1], format_=format_, passages=passages),
        **count_texts(result=result),
    )


def count_texts(result: GenerationResult) -> dict[str, int]:
    texts = [q.question for q in result.questions] + [
        q.solution for q in result.questions
    ]
    texts += [s.text for section in result.sections for s in section.sentences]
    return {
        "texts": len(texts),
        "texts_with_formula": sum(bool(DELIMITER.search(t)) for t in texts),
        "texts_double_backslash": sum(bool(DOUBLE_BACKSLASH.search(t)) for t in texts),
    }


def summarize(runs: list[Run]) -> Tally:
    tally = Tally()
    for run in runs:
        for quote, outcome in run.citations:
            tally.add(quote=quote, outcome=outcome)
    return tally


def rate(counts: Counter[str]) -> str:
    total = sum(counts.values())
    dropped = total - counts[KEPT]
    return f"{dropped}/{total} ({dropped / total:.0%})" if total else "0/0"


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
    truth = json.loads((DATA / "truth.json").read_text(encoding="utf-8"))
    passages = load_passages()
    runs = load_done()
    done = {(run.topic, run.format) for run in runs}
    for number, page in enumerate(truth, start=1):
        ranked = ranked_for(page=number, passages=passages)
        for format_ in FORMATS:
            if (page["title"], format_.value) in done:
                continue
            run = run_one(topic=page["title"], format_=format_, ranked=ranked)
            with RUNS_FILE.open("a", encoding="utf-8") as out:
                out.write(json.dumps(asdict(run), ensure_ascii=False) + "\n")
            cited = len(run.citations)
            print(f"{page['page']} {format_.value}: {run.outcome}, citazioni {cited}")
            runs.append(run)
    return runs


def main() -> int:
    runs = collect_runs()
    tally = summarize(runs=runs)
    total = tally.formula + tally.plain
    report = {
        "runs": [asdict(run) for run in runs],
        "formula": dict(tally.formula),
        "plain": dict(tally.plain),
    }
    (DATA / "citations.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"con formula: {rate(tally.formula)} {dict(tally.formula)}")
    print(f"senza formula: {rate(tally.plain)} {dict(tally.plain)}")
    print(f"totale: {rate(total)}")
    texts = sum(run.texts for run in runs)
    print(
        f"testi: {texts}, con formula fra delimitatori "
        f"{sum(run.texts_with_formula for run in runs)}, con barre doppie "
        f"{sum(run.texts_double_backslash for run in runs)}"
    )
    dropped = sum(total.values()) - total[KEPT]
    over = bool(total) and dropped / sum(total.values()) > DROP_THRESHOLD
    print(f"T069a: {'sì' if over else 'no'} (soglia {DROP_THRESHOLD:.0%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

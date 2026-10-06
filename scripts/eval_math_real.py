"""V10 on real course pages: OCR of formula slides rendered as images.

Measurement script, not part of the suite. It needs Ollama with the OCR
model (on CPU it takes about two minutes a page):

    uv run python scripts/eval_math_real.py "data/prove/Lezioni 11 29 Ottobre.pdf"

The PDF already has a text layer, so the app would not OCR it; here its pages
with the most formula signs are rendered as the OCR action renders them and
read with ocr-v2 through ocr_missing_pages (heading cleanup included). The
text layer is the reference: the script counts delimited formulas, how many
KaTeX parses, "$" delimiters, and how many words of the text layer the OCR
text holds (recall of normalized tokens). Each page is appended to
data/eval/math-real/pages.jsonl as it ends, and skipped on a rerun.
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

from eval_math import DOLLAR_MATH, katex_check, split_formulas
from ollama import Client

from sbobina import ollama_vision
from sbobina.document_models import DocumentStatus
from sbobina.extracted_text import ExtractedText, Page
from sbobina.ocr_pipeline import ocr_missing_pages
from sbobina.pdf_text import extract_pdf_pages, render_pdf_page
from sbobina.settings import settings
from sbobina.study_citations import normalize_tokens

OUT = Path("data/eval/math-real")
PAGES = 10
FORMULA_SIGN = re.compile(r"[=∑∫√≤≥±×÷∂Δ^]")


def formula_pages(texts: tuple[str, ...]) -> list[int]:
    """Indexes of the PAGES pages with the most formula signs, in page order."""
    ranked = sorted(
        range(len(texts)), key=lambda i: -len(FORMULA_SIGN.findall(texts[i]))
    )
    return sorted(i for i in ranked[:PAGES] if FORMULA_SIGN.search(texts[i]))


def ocr_page(client: Client, pdf: Path, index: int) -> tuple[str, float]:
    """The page as the OCR action stores it, and the seconds it took."""
    png = render_pdf_page(path=pdf, index=index, scale=settings.ocr_scale)
    start = time.perf_counter()
    result = ocr_missing_pages(
        extracted=ExtractedText(
            pages=(Page(text="", no_text=True),),
            status=DocumentStatus.READY_NO_TEXT,
            encoding=None,
        ),
        read_page=lambda _: ollama_vision.read_page_image(
            client=client, model=settings.ocr_model, png=png
        ),
        on_progress=lambda done, total: None,
        prompt_version=ollama_vision.PROMPT_VERSION,
    )
    return result.pages[0].text, time.perf_counter() - start


def score(reference: str, text: str) -> dict[str, object]:
    formulas = split_formulas(text)
    parsed = katex_check(expressions=formulas) if formulas else []
    wanted = Counter(normalize_tokens(text=reference))
    found = Counter(normalize_tokens(text=text))
    recalled = sum(min(count, found[token]) for token, count in wanted.items())
    return {
        "formulas": len(formulas),
        "parsable": sum(bool(item["ok"]) for item in parsed),
        "dollars": len(DOLLAR_MATH.findall(text)),
        "reference_signs": len(FORMULA_SIGN.findall(reference)),
        "token_recall": round(recalled / max(1, sum(wanted.values())), 3),
    }


def main(pdf: Path) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    runs = OUT / "pages.jsonl"
    done = (
        {json.loads(line)["page"] for line in runs.read_text().splitlines()}
        if runs.exists()
        else set()
    )
    texts = extract_pdf_pages(path=pdf)
    client = Client(host=settings.ollama_host)
    for index in formula_pages(texts=texts):
        if index + 1 in done:
            continue
        text, seconds = ocr_page(client=client, pdf=pdf, index=index)
        row = {
            "page": index + 1,
            "seconds": round(seconds, 1),
            "reference": texts[index],
            "ocr": text,
        }
        row.update(score(reference=texts[index], text=text))
        with runs.open("a", encoding="utf-8") as out:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(
            f"pagina {index + 1}: {row['formulas']} formule, {row['parsable']} leggibili, $ {row['dollars']}, richiamo {row['token_recall']}, {seconds:.0f} s",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(pdf=Path(sys.argv[1])))

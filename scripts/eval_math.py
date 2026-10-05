"""V10 measure (T060): OCR formula pages with a prompt and score the formulas.

    uv run python scripts/eval_math.py data/eval/math ocr-v2.md

Each page PDF is rendered with the app's own render_pdf_page at the app's OCR
scale and read by the configured vision model with the given prompt, as the
OCR action would. Formulas are extracted with the same delimiter rule as
math-text.js (\\( \\) and \\[ \\], never $); KaTeX (scripts/katex_check.js)
says whether each parses, and a ground-truth formula counts as correct when
some extracted formula has the same MathML. Writes ocr-<prompt>.json next to
the pages and prints one line per page plus the totals.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from ollama import Client

from sbobina import ollama_vision
from sbobina.pdf_text import render_pdf_page
from sbobina.settings import settings

KATEX_CHECK = Path(__file__).with_name("katex_check.js")
DELIMITERS = (("\\(", "\\)"), ("\\[", "\\]"))
# A $...$ pair on one line holding LaTeX syntax (backslash, ^ or _), not a price.
DOLLAR_MATH = re.compile(pattern=r"\$[^$\n]*[\\^_][^$\n]*\$")


def _next_opening(text: str, start: int) -> tuple[int, str, str] | None:
    found = [(text.find(o, start), o, c) for o, c in DELIMITERS]
    hits = [hit for hit in found if hit[0] >= 0]
    return min(hits) if hits else None


def split_formulas(text: str) -> list[str]:
    """Formulas as math-text.js splits them: an opener with no close, or
    whose content repeats the same opener, stays text and scanning resumes."""
    formulas, position = [], 0
    opening = _next_opening(text=text, start=0)
    while opening is not None:
        index, open_token, close_token = opening
        close = text.find(close_token, index + 2)
        value = text[index + 2 : close] if close >= 0 else ""
        if close >= 0 and open_token not in value:
            formulas.append(value)
            position = close + 2
        else:
            position = index + 2
        opening = _next_opening(text=text, start=position)
    return formulas


def katex_check(expressions: list[str]) -> list[dict[str, object]]:
    result = subprocess.run(
        ["node", str(KATEX_CHECK)],
        input=json.dumps(expressions),
        capture_output=True,
        text=True,
        check=True,
    )
    checked: list[dict[str, object]] = json.loads(result.stdout)
    return checked


def read_page(client: Client, pdf: Path, prompt: str) -> tuple[str, float]:
    png = render_pdf_page(path=pdf, index=0, scale=settings.ocr_scale)
    start = time.perf_counter()
    text = ollama_vision.read_page_image(
        client=client, model=settings.ocr_model, png=png, prompt_file=prompt
    )
    return text, time.perf_counter() - start


def score_page(text: str, truth: list[dict[str, object]]) -> dict[str, object]:
    found = split_formulas(text=text)
    checked = katex_check(expressions=found)
    expected = katex_check(expressions=[str(f["latex"]) for f in truth])
    available = Counter(str(c["mathml"]) for c in checked if c["ok"])
    correct = 0
    for item in expected:
        if available[str(item["mathml"])] > 0:
            available[str(item["mathml"])] -= 1
            correct += 1
    return {
        "expected": len(truth),
        "found": len(found),
        "parsable": sum(bool(c["ok"]) for c in checked),
        "correct": correct,
        "dollar_delimiters": len(DOLLAR_MATH.findall(text)),
    }


def main(directory: Path, prompt: str) -> int:
    client = Client(host=settings.ollama_host)
    truth = json.loads((directory / "truth.json").read_text(encoding="utf-8"))
    rows = []
    for page in truth:
        text, seconds = read_page(
            client=client, pdf=directory / f"{page['page']}.pdf", prompt=prompt
        )
        row = {"page": page["page"], "seconds": round(seconds, 1), "text": text}
        row.update(score_page(text=text, truth=page["formulas"]))
        rows.append(row)
        print({k: v for k, v in row.items() if k != "text"})
    totals: dict[str, float] = {
        k: sum(int(r[k]) for r in rows)
        for k in ("expected", "found", "parsable", "correct", "dollar_delimiters")
    }
    totals["seconds_per_page"] = round(
        sum(float(r["seconds"]) for r in rows) / len(rows), 1
    )
    print("TOTALE", totals)
    out = directory / f"ocr-{Path(prompt).stem}.json"
    out.write_text(
        json.dumps({"totals": totals, "pages": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(directory=Path(sys.argv[1]), prompt=sys.argv[2]))

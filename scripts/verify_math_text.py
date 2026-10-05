"""Behaviour check for static/js/math-text.js (T062, plan C4, ADR D5).

Manual verification script, like verify_document_xss.py: the repository has
no JavaScript test runner, so this is not part of `uv run pytest`. Run it by
hand:

    uv run --with playwright python scripts/verify_math_text.py

It drives the system Chrome (``channel="chrome"``) on a blank page with the
vendored KaTeX and math-text.js loaded from disk, renders a table of cases
and exits 1 on the first mismatch, printing every case's outcome.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "src" / "sbobina" / "web" / "static"
KATEX_DIR = STATIC / "vendor" / "katex-0.19.0"
MAX_FORMULA_CHARS = 2000


@dataclass(frozen=True)
class Case:
    name: str
    text: str
    formulas: int
    display: int = 0
    keeps_text: str | None = None


def long_formula(length: int) -> str:
    body = ("x+" * length)[: length - 1] + "x"
    assert len(body) == length
    return "\\(" + body + "\\)"


CASES = (
    Case(name="frazione in linea", text="\\(\\frac{a}{b}\\)", formulas=1),
    Case(
        name="dollari nel testo",
        text="costa 5$ e $6",
        formulas=0,
        keeps_text="costa 5$ e $6",
    ),
    Case(
        name="dollari attorno a formula", text="$x^2$", formulas=0, keeps_text="$x^2$"
    ),
    Case(name="in linea e su riga", text="\\(x\\) e \\[y\\]", formulas=2, display=1),
    Case(
        name="delimitatore aperto",
        text="vale \\(x + 1",
        formulas=0,
        keeps_text="vale \\(x + 1",
    ),
    Case(
        name="markup nel testo", text="<img src=x onerror=alert(1)> \\(x\\)", formulas=1
    ),
    # An unmatched opener must not swallow a later well-formed formula.
    Case(name="aperto poi formula", text="\\[ rotta \\(x+1\\)", formulas=1),
    # LaTeX does not nest \( inside \(: the outer pair stays text.
    Case(
        name="stesso delimitatore annidato",
        text="\\( \\( x \\) \\)",
        formulas=1,
        keeps_text=None,
    ),
)

RENDER = """([text]) => {
  const el = document.createElement('div');
  document.body.appendChild(el);
  window.__calls = 0;
  window.SbobinaMath.renderMathText(el, text);
  return {
    formulas: el.querySelectorAll('.katex').length,
    display: el.querySelectorAll('.katex-display').length,
    text: el.textContent,
    img: el.querySelectorAll('img, script, a').length,
    calls: window.__calls,
    errorSpan: el.querySelectorAll('.katex-error').length,
  };
}"""


def run_case(page: Page, case: Case) -> list[str]:
    result = page.evaluate(RENDER, [case.text])
    problems = []
    if result["formulas"] != case.formulas:
        problems.append(f"formule {result['formulas']} invece di {case.formulas}")
    if result["display"] != case.display:
        problems.append(f"formule su riga {result['display']} invece di {case.display}")
    if case.keeps_text is not None and result["text"] != case.keeps_text:
        problems.append(f"testo {result['text']!r}")
    if result["img"]:
        problems.append("nodi img/script/a creati")
    return problems


def length_problems(page: Page) -> list[str]:
    problems = []
    at_limit = page.evaluate(RENDER, [long_formula(length=MAX_FORMULA_CHARS)])
    over = page.evaluate(RENDER, [long_formula(length=MAX_FORMULA_CHARS + 1)])
    if at_limit["calls"] != 1 or at_limit["formulas"] != 1:
        problems.append(
            f"2000 caratteri: chiamate {at_limit['calls']}, formule {at_limit['formulas']}"
        )
    if (
        over["calls"] != 0
        or over["formulas"] != 0
        or not over["text"].startswith("\\(")
    ):
        problems.append(
            f"2001 caratteri: chiamate {over['calls']}, formule {over['formulas']}"
        )
    return problems


def invalid_problems(page: Page) -> list[str]:
    result = page.evaluate(RENDER, ["\\(\\frac{a}\\)"])
    if "\\frac{a}" not in result["text"]:
        return [f"formula invalida: testo {result['text']!r}"]
    return []


def main() -> int:
    errors: list[str] = []
    failures = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        page = browser.new_page()
        # KaTeX refuses to render in quirks mode: the app pages declare a doctype.
        page.set_content(html="<!doctype html><html><body></body></html>")
        page.on(
            "console", lambda m: errors.append(m.text) if m.type == "error" else None
        )
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_style_tag(path=str(KATEX_DIR / "katex.min.css"))
        page.add_script_tag(path=str(KATEX_DIR / "katex.min.js"))
        page.evaluate(
            "() => { const r = katex.render; katex.render = (...a) => { window.__calls += 1; return r(...a); }; }"
        )
        page.add_script_tag(path=str(STATIC / "js" / "math-text.js"))
        checks = [(case.name, run_case(page=page, case=case)) for case in CASES]
        checks.append(("limite 2000/2001", length_problems(page=page)))
        checks.append(("formula invalida", invalid_problems(page=page)))
        checks.append(("console", errors))
        for name, problems in checks:
            print(f"{'OK  ' if not problems else 'FAIL'} {name}: {'; '.join(problems)}")
            failures += bool(problems)
        browser.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

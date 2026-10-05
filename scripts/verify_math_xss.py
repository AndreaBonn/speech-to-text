"""Adversarial XSS check for formulas on every surface (T066, plan C4, R1).

Manual verification script, like verify_document_xss.py: not part of the
automated suite. Run it by hand:

    uv run --with playwright python scripts/verify_math_xss.py

It starts the app in-process, seeds every surface that renders formulas with
the C4 payloads (math_xss_seed.py), stands in for the grading judge, and
drives the system Chrome over generations, practice, review, chat, study and
document pages. It fails (exit 1) if a dialog fires, an injected script runs,
an img/script node or an on* attribute appears in the page content, KaTeX
creates a link, the page stops responding, or the paired positive formula
\\(x^2\\) is not rendered.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import httpx
import uvicorn
from math_xss_seed import ANSWER, TEXT, seed
from playwright.sync_api import Dialog, Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from sbobina.generation_models import GenerationFormat
from sbobina.ollama_chat import ChatRequest
from sbobina.settings import Settings
from sbobina.web.app import create_app

RESPONSIVE_BUDGET_S = 5.0
REVIEW_CARD_LIMIT = 15
# Lecture quotes (no page in the label) that still show a delimiter as text.
LITERAL_QUOTES = r"""() => [...document.querySelectorAll('.generations__citation')]
  .filter((c) => !c.querySelector('.katex') && c.textContent.includes('\\('))
  .length"""
INSPECT = """() => {
  const main = document.querySelector('main');
  const withHandler = [...main.querySelectorAll('*')].filter(
    (n) => [...n.attributes].some((a) => a.name.startsWith('on'))).length;
  return {
    nodes: main.querySelectorAll('img, script, iframe, object, embed').length,
    handlers: withHandler,
    katexLinks: main.querySelectorAll('.katex a').length,
    formulas: main.querySelectorAll('.katex').length,
    ran: window.__xss || 0,
  };
}"""


def judge(request: ChatRequest) -> str:
    """Stands in for the model: hostile text in the points it is free to write."""
    error = {"frase": ANSWER, "motivo": TEXT}
    return json.dumps(
        {"punti_coperti": [], "punti_mancanti": [TEXT], "errori": [error]}
    )


def start(data_dir: Path) -> tuple[uvicorn.Server, int]:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    app = create_app(settings=Settings(web_port=port), data_dir=data_dir)
    # The app reuses a chat client already on its state: the judge goes there.
    app.state.chat_client = judge
    server = uvicorn.Server(
        uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return server, port


def check(page: Page, name: str, load: Callable[[], None]) -> list[str]:
    """Load a surface within the budget, then inspect what it rendered.

    The budget covers the load itself: a formula that hangs KaTeX (the
    recursive macro) stalls the page before its selector appears.
    """
    page.set_default_timeout(RESPONSIVE_BUDGET_S * 1000)
    try:
        load()
    except PlaywrightTimeoutError:
        print(f"FAIL {name}: not loaded")
        return [f"{name}: page did not respond within {RESPONSIVE_BUDGET_S}s"]
    found = page.evaluate(INSPECT)
    problems = [
        f"{name}: {key}={found[key]}"
        for key in ("nodes", "handlers", "katexLinks", "ran")
        if found[key]
    ]
    if found["formulas"] == 0:
        problems.append(f"{name}: no formula rendered (positive case)")
    print(f"{'OK  ' if not problems else 'FAIL'} {name}: {found}")
    return problems


def attempts(base: str, generation_ids: dict[GenerationFormat, str]) -> tuple[str, str]:
    api = httpx.Client(base_url=base, headers={"Origin": base}, timeout=60)
    prefix = "/api/v1/courses/fisica/generations"
    open_id = generation_ids[GenerationFormat.OPEN]
    graded = api.post(f"{prefix}/{open_id}/attempts").json()["data"]["id"]
    answer = {"text": ANSWER, "answer_id": str(uuid4())}
    api.post(
        f"{prefix}/{open_id}/attempts/{graded}/answers/0", json=answer
    ).raise_for_status()
    api.post(f"{prefix}/{open_id}/attempts/{graded}/answers/0/grade").raise_for_status()
    choice_id = generation_ids[GenerationFormat.MULTIPLE_CHOICE]
    choice = api.post(f"{prefix}/{choice_id}/attempts").json()["data"]["id"]
    return graded, choice


def course_pages(page: Page, base: str) -> list[str]:
    def load() -> None:
        page.goto(f"{base}/corsi?corso=fisica")
        shown = page.get_by_role("button", name="Mostra", exact=True)
        shown.first.wait_for()
        while shown.count():
            shown.first.click()
        page.locator("details").evaluate_all(
            "els => els.forEach(e => { e.open = true; })"
        )
        page.locator(".chat__list-item-open").first.click()
        page.wait_for_selector(".chat__message--assistant")

    problems = check(page=page, name="generazioni e chat", load=load)
    # Quotes are a formula surface too (F67): the payloads must reach them.
    if not page.locator(".generations__citation .katex").count():
        problems.append("citazioni: no formula rendered (positive case)")
    # Lecture quotes are transcripts and stay literal (D5).
    literal = page.evaluate(LITERAL_QUOTES)
    if not literal:
        problems.append("citazioni da lezione: delimiters not shown as text")
    return problems


def review_page(page: Page, base: str) -> list[str]:
    def load() -> None:
        page.goto(f"{base}/ripasso")
        page.get_by_role("button", name="Ripassa").click()
        front = page.locator("#ripasso-card-front")
        for _ in range(REVIEW_CARD_LIMIT):
            page.wait_for_selector("#ripasso-card-front:not(:empty)")
            # Only the payload card holds formulas.
            if front.locator(".katex").count():
                break
            shown = front.inner_text()
            page.click("#ripasso-card-reveal")
            page.click(".review-card__rating[data-rating='3']")
            # Wait for the next card, not a fixed delay: the old one stays a moment.
            page.wait_for_function(
                "text => document.querySelector('#ripasso-card-front').innerText"
                " !== text",
                arg=shown,
            )
        page.click("#ripasso-card-reveal")

    return check(page=page, name="ripasso", load=load)


def visit(page: Page, url: str, selector: str, name: str) -> list[str]:
    def load() -> None:
        page.goto(url)
        page.wait_for_selector(selector)

    return check(page=page, name=name, load=load)


def practice_pages(page: Page, base: str, ids: tuple[str, str]) -> list[str]:
    problems = []
    for attempt_id in ids:
        url = f"{base}/corsi/fisica/esercitazioni/{attempt_id}"
        problems += visit(
            page=page,
            url=url,
            selector=".practice-question__text",
            name="esercitazione",
        )
        # The graded attempt (first id) shows the source quotes (F67).
        if (
            attempt_id == ids[0]
            and not page.locator(".practice-result__citations .katex").count()
        ):
            problems.append("citazioni esito: no formula rendered (positive case)")
    return problems + review_page(page=page, base=base)


def material_pages(page: Page, base: str, job_id: str, doc_id: str) -> list[str]:
    studio = visit(
        page=page,
        url=f"{base}/studio/{job_id}",
        selector=".study__chapter",
        name="studio",
    )
    url = f"{base}/corsi/fisica/documenti/{doc_id}"
    return studio + visit(
        page=page, url=url, selector=".document__paragraph", name="documento"
    )


def run(base: str, job_id: str, doc_id: str, ids: tuple[str, str]) -> list[str]:
    dialogs: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        page = browser.new_page()

        def record_dialog(dialog: Dialog) -> None:
            dialogs.append(dialog.message)
            dialog.dismiss()

        page.on("dialog", record_dialog)
        # CSP reports land in the console (F75: KaTeX's inline error style).
        errors: list[str] = []
        page.on(
            "console", lambda m: errors.append(m.text) if m.type == "error" else None
        )
        problems = course_pages(page=page, base=base)
        problems += practice_pages(page=page, base=base, ids=ids)
        problems += material_pages(page=page, base=base, job_id=job_id, doc_id=doc_id)
        browser.close()
    problems += [f"{len(errors)} console error(s): {errors[:3]}"] * bool(errors)
    return problems + [f"{len(dialogs)} dialog(s): {dialogs}"] * bool(dialogs)


def main() -> int:
    with TemporaryDirectory() as tmp:
        source, generation_ids = seed(data_dir=Path(tmp))
        server, port = start(data_dir=Path(tmp))
        base = f"http://127.0.0.1:{port}"
        ids = attempts(base=base, generation_ids=generation_ids)
        problems = run(
            base=base, job_id=source.job_ids[0], doc_id=source.doc_id, ids=ids
        )
        server.should_exit = True
    for problem in problems:
        print(f"FAIL: {problem}")
    if not problems:
        print(
            "PASS: no dialog, no injected node or handler, no KaTeX link, positive case rendered"
        )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

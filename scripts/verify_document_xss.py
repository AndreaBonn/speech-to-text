"""Adversarial XSS check for course document pages (T016/T017).

Manual verification script: this repository has no Playwright test
infrastructure yet (no browsers installed, no pytest-playwright fixture),
so this script is NOT part of the automated suite. It is not run by
`uv run pytest` and not run by CI. Run it by hand after installing
Playwright and a Chrome browser:

    uv run --with playwright python scripts/verify_document_xss.py

It drives the system Chrome (``channel="chrome"``), so no Playwright browser
download is needed.

It starts the app in-process on a local port, seeds a course with a
document whose filename and extracted text both carry `<script>` and
`<img onerror=...>` payloads, then drives a real browser over the course
materials list and the document reading page. It fails (exit 1) if any
injected `<script>`/`<img>` node lands in the DOM, if the payload runs
(tracked via `window.__xss`), or if any dialog (confirm/alert/prompt)
fires on its own.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from sbobina.course_registry import get_or_create
from sbobina.document_models import (
    CourseDocument,
    DocumentKind,
    DocumentStatus,
)
from sbobina.extracted_text import ExtractedText, Page
from sbobina.settings import Settings
from sbobina.web.app import create_app
from sbobina.web.document_store import write_document, write_text

PAYLOAD_SCRIPT = "<script>window.__xss = (window.__xss || 0) + 1;</script>"
PAYLOAD_IMG = '<img src=x onerror="window.__xss = (window.__xss || 0) + 1">'
FILENAME = f"Manuale{PAYLOAD_SCRIPT}{PAYLOAD_IMG}.pdf"
TEXT = f"Introduzione {PAYLOAD_SCRIPT} {PAYLOAD_IMG} al corso."
DOC_ID = "11111111-1111-1111-1111-111111111111"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _seed(data_dir: Path) -> str:
    """Write a course and a ready document whose filename/text carry payloads."""
    courses_dir = data_dir / "courses"
    course = get_or_create(courses_dir=courses_dir, key="sicurezza", label="Sicurezza")
    doc_dir = courses_dir / course.id / "documents" / DOC_ID
    doc_dir.mkdir(parents=True)
    document = CourseDocument(
        id=DOC_ID,
        course_id=course.id,
        filename=FILENAME,
        kind=DocumentKind.PDF,
        size=1,
        sha256="0" * 64,
        status=DocumentStatus.READY,
        error=None,
        pages=1,
        created_at=datetime.now(tz=UTC),
    )
    write_document(courses_dir=courses_dir, document=document)
    write_text(
        doc_dir=doc_dir,
        extracted=ExtractedText(
            pages=(Page(text=TEXT, no_text=False),),
            status=DocumentStatus.READY,
            encoding="utf-8",
        ),
    )
    return course.key


def _start_server(data_dir: Path) -> tuple[uvicorn.Server, threading.Thread, int]:
    app = create_app(settings=Settings(), data_dir=data_dir)
    port = _free_port()
    config = uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    return server, thread, port


def _check_page(page: object, url: str, wait_selector: str, scope: str) -> list[str]:
    failures = []
    page.goto(url)  # type: ignore[attr-defined]
    page.wait_for_selector(wait_selector)  # type: ignore[attr-defined]
    scripts = page.eval_on_selector_all(f"{scope} script", "nodes => nodes.length")  # type: ignore[attr-defined]
    imgs = page.eval_on_selector_all(f"{scope} img", "nodes => nodes.length")  # type: ignore[attr-defined]
    if scripts:
        failures.append(f"{url}: injected {scripts} <script> node(s) in {scope}")
    if imgs:
        failures.append(f"{url}: injected {imgs} <img> node(s) in {scope}")
    return failures


def main() -> int:
    from playwright.sync_api import Dialog, sync_playwright

    with TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        key = _seed(data_dir)
        server, thread, port = _start_server(data_dir)
        base = f"http://127.0.0.1:{port}"

        dialogs: list[str] = []
        failures: list[str] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            page = browser.new_page()

            def record_dialog(dialog: Dialog) -> None:
                dialogs.append(dialog.message)
                dialog.dismiss()

            page.on("dialog", record_dialog)

            failures += _check_page(
                page,
                f"{base}/corsi?corso={key}",
                "#materials-list li",
                "#materials-list",
            )
            failures += _check_page(
                page,
                f"{base}/corsi/{key}/documenti/{DOC_ID}",
                "#document-text .document__paragraph",
                "#document-text",
            )

            executed = page.evaluate("window.__xss || 0")
            if executed:
                failures.append(f"payload executed {executed} time(s)")
            if dialogs:
                failures.append(f"{len(dialogs)} dialog(s) fired: {dialogs}")

            browser.close()

        server.should_exit = True
        thread.join(timeout=5)

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("PASS: no injected script/img nodes, no dialog, payload never executed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

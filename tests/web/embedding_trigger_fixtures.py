import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from test_extraction_worker import FAKE_RUNNER
from test_supervisor import Harness

from sbobina import ollama_embed
from sbobina.document_models import DocumentStatus
from sbobina.ollama_embed import ModelStatus
from sbobina.settings import settings
from sbobina.web.app import create_app
from sbobina.web.document_store import read_document, write_document
from sbobina.web.extraction_worker import ExtractionWorkerOptions
from sbobina.web.job_store import JobStore

OCR_RUNNER = """
import json
import sys
from pathlib import Path

stage, directory = sys.argv[1:]
path = Path(directory)
record = json.loads((path / 'document.json').read_text())
record['status'] = 'ready_no_text' if (path / 'no-text').exists() else 'ready'
(path / 'document.json').write_text(json.dumps(record))
"""


@pytest.fixture
def installed_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "semantic_search", True)
    monkeypatch.setattr(
        ollama_embed,
        "model_status",
        lambda **kwargs: ModelStatus(digest="installed", dimensions=2),
    )


@pytest.fixture
def extraction_app(tmp_path: Path) -> FastAPI:
    runner = tmp_path / "extraction_trigger_child.py"
    runner.write_text(
        FAKE_RUNNER
        + "\nif (path / 'no-text').exists():\n"
        + "    (path / 'text.json').write_text(json.dumps(\n"
        + "        {'pages': [{'text': '', 'no_text': True}],\n"
        + "         'status': 'ready_no_text', 'encoding': None}))\n",
        encoding="utf-8",
    )
    return create_app(
        settings=settings,
        data_dir=tmp_path,
        extraction_worker_options=ExtractionWorkerOptions(
            command=(sys.executable, str(runner)), timeout_s=5
        ),
    )


def install_ocr_child(harness: Harness) -> None:
    runner = harness.store.jobs_dir.parent / "fake_runner.py"
    runner.write_text(OCR_RUNNER, encoding="utf-8")


def prepare_extraction(store: JobStore, course_id: str, doc_id: str) -> None:
    document = read_document(
        courses_dir=store.courses_dir, course_id=course_id, doc_id=doc_id
    )
    write_document(
        courses_dir=store.courses_dir,
        document=replace(document, status=DocumentStatus.EXTRACTING, pages=None),
    )

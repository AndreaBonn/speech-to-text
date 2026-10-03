"""Child-process execution of the "ocr" stage (T051, second half).

Mirrors generation_runner.py's split: ``run_ocr`` is unit-testable with an
injected ``ReadPage``, ``run_ocr_stage`` is the production entry point that
builds the real Ollama vision client and the pdfium page renderer.
"""

from dataclasses import replace
from pathlib import Path

from ollama import Client

from sbobina import llm_corrector
from sbobina.document_models import CourseDocument
from sbobina.extracted_text import ExtractedText
from sbobina.ocr_pipeline import ReadPage, ocr_missing_pages
from sbobina.ollama_vision import read_page_image
from sbobina.pdf_text import render_pdf_page
from sbobina.settings import settings
from sbobina.web.document_store import (
    StoredText,
    mark_extracted,
    original_path,
    read_document_in,
    read_text,
    write_text,
)
from sbobina.web.ocr_store import OcrStatus, load_ocr, save_ocr


def _course_and_doc_id(document_dir: Path) -> tuple[str, str]:
    """document_dir is courses/<course_id>/documents/<doc_id>."""
    return document_dir.parent.parent.name, document_dir.name


def _write_progress(
    courses_dir: Path, course_id: str, doc_id: str, done: int, total: int
) -> None:
    record = load_ocr(courses_dir=courses_dir, course_id=course_id, doc_id=doc_id)
    if record is None:
        return
    save_ocr(
        courses_dir=courses_dir,
        course_id=course_id,
        doc_id=doc_id,
        record=replace(record, done=done, total=total),
    )


def run_ocr(document_dir: Path, read_page: ReadPage) -> None:
    """Fill in ``no_text`` pages for the document in ``document_dir``.

    Raises whatever ``read_page`` raises (e.g. ``CorrectorUnavailableError``
    when Ollama is unreachable): ``text.json``/``document.json`` are only
    written after every missing page succeeded, so a mid-run failure leaves
    both, and the original file, untouched.
    """
    courses_dir = document_dir.parent.parent.parent
    course_id, doc_id = _course_and_doc_id(document_dir=document_dir)
    stored = read_text(doc_dir=document_dir)
    extracted = ExtractedText(
        pages=stored.pages, status=stored.status, encoding=stored.encoding
    )

    def on_progress(done: int, total: int) -> None:
        _write_progress(
            courses_dir=courses_dir,
            course_id=course_id,
            doc_id=doc_id,
            done=done,
            total=total,
        )

    result = ocr_missing_pages(
        extracted=extracted, read_page=read_page, on_progress=on_progress
    )
    _persist(document_dir=document_dir, result=result)


def _persist(document_dir: Path, result: ExtractedText) -> None:
    """Write the text, then the document state, then mark the run done."""
    courses_dir = document_dir.parent.parent.parent
    course_id, doc_id = _course_and_doc_id(document_dir=document_dir)
    write_text(doc_dir=document_dir, extracted=result)
    mark_extracted(
        courses_dir=courses_dir,
        course_id=course_id,
        doc_id=doc_id,
        result=StoredText(
            pages=result.pages, status=result.status, encoding=result.encoding
        ),
    )
    record = load_ocr(courses_dir=courses_dir, course_id=course_id, doc_id=doc_id)
    if record is not None:
        save_ocr(
            courses_dir=courses_dir,
            course_id=course_id,
            doc_id=doc_id,
            record=replace(record, status=OcrStatus.DONE),
        )


def _build_read_page(document_dir: Path, document: CourseDocument) -> ReadPage:
    llm_corrector.ensure_model(model=settings.ocr_model, host=settings.ollama_host)
    client = Client(host=settings.ollama_host, timeout=settings.ocr_timeout_s)
    source = original_path(doc_dir=document_dir, kind=document.kind)

    def read_page(index: int) -> str:
        png = render_pdf_page(path=source, index=index, scale=settings.ocr_scale)
        return read_page_image(client=client, model=settings.ocr_model, png=png)

    return read_page


def run_ocr_stage(document_dir: Path) -> None:
    """Production entry point: document_dir is courses/<course_id>/documents/<doc_id>."""
    document = read_document_in(doc_dir=document_dir)
    read_page = _build_read_page(document_dir=document_dir, document=document)
    run_ocr(document_dir=document_dir, read_page=read_page)


__all__ = ["run_ocr", "run_ocr_stage"]

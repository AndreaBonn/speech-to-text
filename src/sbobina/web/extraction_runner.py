"""Child process entry point for document text extraction (T014, D4).

Invoked as ``python -m sbobina.web.extraction_runner extract <doc_dir> <max_memory_mb>``.
Isolates the server from a parser that crashes, loops or exhausts memory: the
memory limit is applied here, in the child, before the untrusted file is
opened. The parent (``extraction_worker.py``) owns the timeout and the
document status transitions; this process only ever produces ``text.json``.
"""

import logging
import sys
from pathlib import Path

from sbobina.document_extract import extract
from sbobina.web.child_limits import _apply_memory_limit
from sbobina.web.document_store import original_path, read_document_in, write_text

__all__ = ["_apply_memory_limit", "extract", "main", "run_extraction"]

logger = logging.getLogger("sbobina")
EXTRACT_COMMAND = "extract"


def run_extraction(doc_dir: Path, max_memory_mb: int) -> None:
    """Extract the document in ``doc_dir`` and write ``text.json``; raises on failure."""
    _apply_memory_limit(max_memory_mb=max_memory_mb)
    document = read_document_in(doc_dir=doc_dir)
    source = original_path(doc_dir=doc_dir, kind=document.kind)
    extracted = extract(path=source, kind=document.kind)
    write_text(doc_dir=doc_dir, extracted=extracted)


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] != EXTRACT_COMMAND:
        logger.error("Uso: extraction_runner extract <doc_dir> <max_memory_mb>")
        return 2
    try:
        run_extraction(doc_dir=Path(argv[1]), max_memory_mb=int(argv[2]))
    except Exception:
        logger.exception("Estrazione fallita per %s", argv[1])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

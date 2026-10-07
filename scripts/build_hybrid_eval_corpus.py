"""Build the isolated retrieval-hybrid eval corpus (T011, specs/004-hybrid-retrieval).

Writes a standalone data dir, usable by the app's own code, at
``data/eval/retrieval-hybrid/corpus/``:

- course "economia aziendale": every PDF in ``data/prove/`` except the exam
  (``EcAziendale2017_domande_esame_*.pdf``, excluded as in T024: it is the
  source of the `exam` gold questions, not corpus material), plus the two
  English-language chapters in ``data/eval/retrieval-hybrid/english-staging/``
  (synthetic material for the `crosslingual` gold questions), all extracted
  with the production document pipeline (``document_sniff``,
  ``document_store``, ``extraction_runner``).
- course "diritto": a copy of the three complete lectures in ``data/jobs/``
  (the fourth job there, ``77593c93-...``, has no transcript and is not
  copied).

Usage: ``uv run python scripts/build_hybrid_eval_corpus.py``
"""

import hashlib
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sbobina.course_registry import get_or_create
from sbobina.document_models import CourseDocument, DocumentStatus
from sbobina.document_sniff import sniff_document
from sbobina.web.api_jobs import source_name
from sbobina.web.document_store import (
    document_dir,
    mark_extracted,
    original_path,
    read_text,
    write_document,
)
from sbobina.web.extraction_runner import run_extraction

REPO_ROOT = Path(__file__).resolve().parent.parent
PROVE_DIR = REPO_ROOT / "data" / "prove"
JOBS_DIR = REPO_ROOT / "data" / "jobs"
ENGLISH_STAGING_DIR = (
    REPO_ROOT / "data" / "eval" / "retrieval-hybrid" / "english-staging"
)
CORPUS_DIR = REPO_ROOT / "data" / "eval" / "retrieval-hybrid" / "corpus"
EXAM_PREFIX = "EcAziendale2017_domande_esame"
# The three jobs with a readable transcript (original or corrected): the
# fourth job for the same course, 77593c93-..., stayed in "transcribing" and
# has no audio.json, so it is not a complete lecture.
DIRITTO_JOB_IDS = (
    "7aef7b66-2f4c-4f4c-9cb8-4848faa0bbaf",
    "82144973-acfa-4b8b-ab8b-90c8ef51e85e",
    "8319d0b3-8367-48ec-b844-4c4e29b737b0",
)
# The raw audio and the child process log are not needed for retrieval and
# are large (30-40 MB each); everything else (job.json, progress.json,
# transcripts, correction report) is copied as-is.
SKIP_JOB_FILES = {"audio.m4a", "child.log"}
MAX_EXTRACT_MEMORY_MB = 2048


def _upload_document(courses_dir: Path, course_id: str, path: Path) -> CourseDocument:
    """Copy one source file into the course and extract it, like a real upload."""
    data = path.read_bytes()
    kind = sniff_document(head=data[:32], path=path, filename=path.name)
    if kind is None:
        raise ValueError(f"Formato non riconosciuto: {path}")
    doc_id = str(uuid4())
    doc_dir = document_dir(courses_dir=courses_dir, course_id=course_id, doc_id=doc_id)
    doc_dir.mkdir(parents=True)
    original_path(doc_dir=doc_dir, kind=kind).write_bytes(data)
    document = CourseDocument(
        id=doc_id,
        course_id=course_id,
        filename=source_name(filename=path.name),
        kind=kind,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        status=DocumentStatus.EXTRACTING,
        error=None,
        pages=None,
        created_at=datetime.now(tz=UTC),
    )
    write_document(courses_dir=courses_dir, document=document)
    run_extraction(doc_dir=doc_dir, max_memory_mb=MAX_EXTRACT_MEMORY_MB)
    return mark_extracted(
        courses_dir=courses_dir,
        course_id=course_id,
        doc_id=doc_id,
        result=read_text(doc_dir=doc_dir),
    )


def _build_economia_aziendale(courses_dir: Path) -> list[CourseDocument]:
    course = get_or_create(
        courses_dir=courses_dir, key="economia aziendale", label="Economia aziendale"
    )
    pdfs = sorted(
        path
        for path in PROVE_DIR.glob("*.pdf")
        if not path.name.startswith(EXAM_PREFIX)
    )
    english_chapters = sorted(ENGLISH_STAGING_DIR.glob("*.md"))
    return [
        _upload_document(courses_dir=courses_dir, course_id=course.id, path=path)
        for path in [*pdfs, *english_chapters]
    ]


def _copy_job(jobs_dir: Path, job_id: str) -> None:
    source = JOBS_DIR / job_id
    target = jobs_dir / job_id
    target.mkdir(parents=True)
    for item in source.iterdir():
        if item.is_file() and item.name not in SKIP_JOB_FILES:
            shutil.copyfile(item, target / item.name)


def _build_diritto(courses_dir: Path, jobs_dir: Path) -> int:
    get_or_create(courses_dir=courses_dir, key="diritto", label="Diritto")
    for job_id in DIRITTO_JOB_IDS:
        _copy_job(jobs_dir=jobs_dir, job_id=job_id)
    return len(DIRITTO_JOB_IDS)


def main() -> None:
    if CORPUS_DIR.exists():
        print(f"gia' presente, ricreo: {CORPUS_DIR}", file=sys.stderr)
        shutil.rmtree(CORPUS_DIR)
    courses_dir = CORPUS_DIR / "courses"
    jobs_dir = CORPUS_DIR / "jobs"
    courses_dir.mkdir(parents=True)
    jobs_dir.mkdir(parents=True)
    documents = _build_economia_aziendale(courses_dir=courses_dir)
    lecture_count = _build_diritto(courses_dir=courses_dir, jobs_dir=jobs_dir)
    ready = sum(doc.status is DocumentStatus.READY for doc in documents)
    print(f"documenti: {len(documents)} (ready: {ready})")
    for doc in documents:
        print(f"  {doc.filename}: {doc.status.value}, {doc.pages} pagine")
    print(f"lezioni diritto: {lecture_count}")
    not_ready = [
        doc.filename for doc in documents if doc.status is not DocumentStatus.READY
    ]
    if not_ready:
        # A partly extracted corpus would fail its gold pages with no visible cause.
        sys.exit(f"documenti non pronti, corpus inutilizzabile: {', '.join(not_ready)}")


if __name__ == "__main__":
    main()

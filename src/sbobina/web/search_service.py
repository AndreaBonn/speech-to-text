import logging
from collections.abc import Callable, Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from sbobina.document_models import DocumentStatus
from sbobina.document_passages import DocumentPassage, chunk_document_pages
from sbobina.models import load_transcript
from sbobina.search_text import Passage, passages_from_transcript
from sbobina.web.api_files import TRANSCRIPT_FILES
from sbobina.web.document_index import DocumentState
from sbobina.web.document_store import (
    DOCUMENT_FILENAME,
    TEXT_FILENAME,
    read_document_in,
    read_text,
)
from sbobina.web.job_store import JobStore
from sbobina.web.search_index import (
    LectureHit,
    LectureState,
    SearchCorruptError,
    SearchHit,
    SearchIndex,
    SearchPage,
    Variant,
    index_session,
)

logger = logging.getLogger(__name__)

_SEARCH_LOCK = Lock()
PREFERRED_VARIANTS: tuple[Variant, ...] = ("corrected", "original")


@dataclass(frozen=True)
class SearchQuery:
    match: str
    job_ids: Collection[str] | None
    limit: int
    offset: int


@dataclass(frozen=True)
class LectureResult:
    lecture: LectureHit
    passages: list[SearchHit]


@dataclass(frozen=True)
class LectureResults:
    items: list[LectureResult]
    total: int


def _preferred_transcript(directory: Path) -> tuple[Path, LectureState] | None:
    for variant in PREFERRED_VARIANTS:
        path = directory / TRANSCRIPT_FILES[variant]
        try:
            status = path.stat()
        except FileNotFoundError:
            continue
        return path, LectureState(
            variant=variant, path_mtime_ns=status.st_mtime_ns, path_size=status.st_size
        )
    return None


def _read_passages(path: Path) -> list[Passage] | None:
    """Passages of one transcript, or None when it cannot be read right now.

    A job deleted mid-scan or a transcript caught mid-write must not break the
    search over every other lecture: the caller skips it until the next scan.
    """
    try:
        return passages_from_transcript(transcript=load_transcript(path=path))
    except (OSError, ValueError, KeyError, TypeError) as error:
        logger.warning("Trascrizione non leggibile, salto %s: %s", path, error)
        return None


def _reconcile(store: JobStore, index: SearchIndex) -> int:
    """Bring lectures and course documents in the index in line with disk."""
    return _reconcile_lectures(store=store, index=index) + _reconcile_documents(
        courses_dir=store.courses_dir, index=index
    )


def _reconcile_lectures(store: JobStore, index: SearchIndex) -> int:
    indexed = index.indexed_lectures()
    present = set()
    replaced = 0
    for directory in store.jobs_dir.glob("*"):
        if not directory.is_dir():
            continue
        preferred = _preferred_transcript(directory=directory)
        if preferred is None:
            continue
        path, state = preferred
        job_id = directory.name
        present.add(job_id)
        if indexed.get(job_id) == state:
            continue
        passages = _read_passages(path=path)
        if passages is None:
            continue
        index.replace_lecture(job_id=job_id, state=state, passages=passages)
        replaced += 1
    for job_id in indexed.keys() - present:
        index.remove_lecture(job_id=job_id)
    return replaced


def _read_document_passages(doc_dir: Path, doc_id: str) -> list[DocumentPassage] | None:
    """Passages of one document's extracted text, or None when unreadable now.

    A document mid-write (extraction still in progress) must not break the
    search over every other document: the caller skips it until the next scan.
    """
    try:
        stored = read_text(doc_dir=doc_dir)
    except (OSError, ValueError, KeyError, TypeError) as error:
        logger.warning("Testo documento non leggibile, salto %s: %s", doc_dir, error)
        return None
    return chunk_document_pages(doc_id=doc_id, pages=stored.pages)


def _ready_document_state(document_path: Path) -> DocumentState | None:
    """State of a READY document's text, or None when it must not be indexed."""
    doc_dir = document_path.parent
    try:
        document = read_document_in(doc_dir=doc_dir)
    except (OSError, ValueError, KeyError, TypeError) as error:
        logger.warning("Documento non leggibile, salto %s: %s", doc_dir, error)
        return None
    if document.status is not DocumentStatus.READY:
        return None
    try:
        text_stat = (doc_dir / TEXT_FILENAME).stat()
    except FileNotFoundError:
        return None
    return DocumentState(
        course_id=doc_dir.parent.parent.name,
        text_mtime_ns=text_stat.st_mtime_ns,
        text_size=text_stat.st_size,
    )


def _reconcile_documents(courses_dir: Path, index: SearchIndex) -> int:
    indexed = index.indexed_documents()
    present: set[str] = set()
    replaced = 0
    for document_path in courses_dir.glob(f"*/documents/*/{DOCUMENT_FILENAME}"):
        state = _ready_document_state(document_path=document_path)
        if state is None:
            continue
        doc_dir = document_path.parent
        present.add(doc_dir.name)
        if indexed.get(doc_dir.name) == state:
            continue
        passages = _read_document_passages(doc_dir=doc_dir, doc_id=doc_dir.name)
        if passages is None:
            continue
        index.replace_document(doc_id=doc_dir.name, state=state, passages=passages)
        replaced += 1
    for doc_id in indexed.keys() - present:
        index.remove_document(doc_id=doc_id)
    return replaced


def reconcile(store: JobStore, index: SearchIndex) -> int:
    """Reconcile under the shared lock and return the number of reindexed items."""
    with _SEARCH_LOCK:
        return _reconcile(store=store, index=index)


@contextmanager
def search_session(store: JobStore, path: Path) -> Iterator[SearchIndex]:
    """Keep one lock and one connection through reconciliation and all queries.

    Corruption discards the index and raises SearchCorruptError. Use search()
    when the entire operation must be replayed automatically after rebuilding.
    """
    with _SEARCH_LOCK, index_session(path=path) as index:
        _reconcile(store=store, index=index)
        yield index


def _search_once(store: JobStore, path: Path, query: SearchQuery) -> SearchPage:
    with index_session(path=path) as index:
        _reconcile(store=store, index=index)
        return index.search(
            match=query.match,
            job_ids=query.job_ids,
            limit=query.limit,
            offset=query.offset,
        )


def _lectures_once(
    store: JobStore, path: Path, query: SearchQuery, passages_per_lecture: int
) -> LectureResults:
    with index_session(path=path) as index:
        _reconcile(store=store, index=index)
        page = index.search_lectures(
            match=query.match,
            job_ids=query.job_ids,
            page=(query.limit, query.offset),
        )
        items = [
            LectureResult(
                lecture=hit,
                passages=index.search(
                    match=query.match,
                    job_ids=[hit.job_id],
                    limit=passages_per_lecture,
                    offset=0,
                ).items,
            )
            for hit in page.items
        ]
        return LectureResults(items=items, total=page.total)


def _with_rebuild[T](run: Callable[[], T]) -> T:
    """Run under the shared lock; replay once after a corrupt index is discarded."""
    with _SEARCH_LOCK:
        try:
            return run()
        except SearchCorruptError:
            return run()


def search(store: JobStore, path: Path, query: SearchQuery) -> SearchPage:
    """Reconcile and query passages atomically; rebuild once on corruption."""
    return _with_rebuild(lambda: _search_once(store=store, path=path, query=query))


def search_lectures(
    store: JobStore, path: Path, query: SearchQuery, passages_per_lecture: int
) -> LectureResults:
    """Page lectures (limit/offset count lectures) with their best passages."""
    return _with_rebuild(
        lambda: _lectures_once(
            store=store,
            path=path,
            query=query,
            passages_per_lecture=passages_per_lecture,
        )
    )

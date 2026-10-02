import logging
from collections.abc import Callable, Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from sbobina.models import load_transcript
from sbobina.search_text import Passage, passages_from_transcript
from sbobina.web.api_files import TRANSCRIPT_FILES
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


def reconcile(store: JobStore, index: SearchIndex) -> int:
    """Reconcile under the shared lock and return the number of reindexed jobs."""
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

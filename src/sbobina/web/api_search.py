from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field

from sbobina.course_registry import CourseRecord, find_by_key, iter_courses
from sbobina.courses import effective_course
from sbobina.document_models import CourseDocument
from sbobina.search_text import build_match_query
from sbobina.web import search_service
from sbobina.web.document_index import DocumentHit
from sbobina.web.document_store import read_document
from sbobina.web.errors import NotFoundError
from sbobina.web.job_store import JobStore
from sbobina.web.lecture_title import reader_title
from sbobina.web.search_index import SearchHit
from sbobina.web.search_service import (
    DocumentSearchQuery,
    LectureResult,
    LectureResults,
    SearchQuery,
)

router = APIRouter(prefix="/api/v1")

SEARCH_COURSE_JOB_LIMIT = 100_000
SEARCH_PASSAGES_PER_LECTURE = 3
SEARCH_DOCUMENT_RESULTS_LIMIT = 10


class SearchParameters(BaseModel):
    q: str
    course: str | None = None
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1)


def _course_job_ids(store: JobStore, course: str | None) -> list[str] | None:
    if course is None:
        return None
    return [
        str(record.id)
        for record in store.list(
            course_key=course, page=1, per_page=SEARCH_COURSE_JOB_LIMIT
        ).items
    ]


def _passage_payload(hit: SearchHit) -> dict[str, Any]:
    return {
        "start": hit.start,
        "variant": hit.variant,
        "snippet": jsonable_encoder(hit.snippet),
        "href": f"/lettore/{hit.job_id}?t={hit.start}&variant={hit.variant}",
    }


def _lecture_payload(store: JobStore, result: LectureResult) -> dict[str, Any]:
    job_id = result.lecture.job_id
    record = store.get(job_id=job_id)
    meta = store.read_meta(job_id=job_id)
    return {
        "id": job_id,
        "title": reader_title(record=record),
        "course": effective_course(course=meta.course, subject=record.config.subject),
        "passage_count": result.lecture.passage_count,
        "passages": [_passage_payload(hit=hit) for hit in result.passages],
    }


def _document_course_filter(
    courses_dir: Path, course: str | None
) -> tuple[str | None, bool]:
    """Course id to scope document search to; False means "no course matches".

    A course key with no registry entry (never had a document) must yield no
    document results rather than silently searching every course.
    """
    if course is None:
        return None, True
    registered = find_by_key(courses_dir=courses_dir, key=course)
    return (registered.id, True) if registered is not None else (None, False)


def _document_href(course: CourseRecord, doc_id: str, page: int, query: str) -> str:
    return (
        f"/corsi/{quote(course.key, safe='')}/documenti/{doc_id}"
        f"?p={page}&q={quote(query, safe='')}"
    )


def _document_payload(
    document: CourseDocument, course: CourseRecord, hit: DocumentHit, query: str
) -> dict[str, Any]:
    return {
        "kind": "document",
        "doc_id": hit.doc_id,
        "filename": document.filename,
        "course": course.label,
        "page": hit.page,
        "snippet": jsonable_encoder(hit.snippet),
        "href": _document_href(
            course=course, doc_id=hit.doc_id, page=hit.page, query=query
        ),
    }


def _document_results(
    store: JobStore, path: Path, query: DocumentSearchQuery, raw_query: str
) -> tuple[list[dict[str, Any]], int]:
    """Document hits shown on a results page, and how many passages matched."""
    page = search_service.search_documents(store=store, path=path, query=query)
    # One registry read per search, not one per hit.
    courses = {
        course.id: course for course in iter_courses(courses_dir=store.courses_dir)
    }
    items = []
    for hit in page.items:
        course = courses.get(hit.course_id)
        if course is None:
            continue
        try:
            document = read_document(
                courses_dir=store.courses_dir,
                course_id=hit.course_id,
                doc_id=hit.doc_id,
            )
        except NotFoundError:
            continue  # deleted between the indexed search and this read
        items.append(
            _document_payload(
                document=document, course=course, hit=hit, query=raw_query
            )
        )
    return items, page.total


def _search_response(
    store: JobStore,
    results: LectureResults,
    parameters: SearchParameters,
    documents: tuple[list[dict[str, Any]], int],
) -> dict[str, Any]:
    # Pagination describes lectures. Document hits are additive items, at most
    # SEARCH_DOCUMENT_RESULTS_LIMIT and on page 1 only; documents_total tells
    # the client how many document passages matched in all.
    document_items, documents_total = documents
    total = results.total
    lecture_items = [
        _lecture_payload(store=store, result=result) for result in results.items
    ]
    return {
        "data": lecture_items + (document_items if parameters.page == 1 else []),
        "meta": {
            "page": parameters.page,
            "per_page": parameters.per_page,
            "total": total,
            "total_pages": (total + parameters.per_page - 1) // parameters.per_page,
            "documents_total": documents_total,
        },
    }


@router.get("/search")
def search_lectures(
    request: Request, parameters: Annotated[SearchParameters, Query()]
) -> dict[str, Any]:
    match = build_match_query(raw=parameters.q)
    if match is None:
        raise RequestValidationError(
            errors=[
                {
                    "loc": ("q",),
                    "msg": "Inserisci almeno un termine di ricerca valido",
                    "type": "value_error",
                }
            ]
        )
    store: JobStore = request.app.state.job_store
    path = request.app.state.search_index_path
    results = search_service.search_lectures(
        store=store,
        path=path,
        query=SearchQuery(
            match=match,
            job_ids=_course_job_ids(store=store, course=parameters.course),
            limit=parameters.per_page,
            offset=(parameters.page - 1) * parameters.per_page,
        ),
        passages_per_lecture=SEARCH_PASSAGES_PER_LECTURE,
    )
    document_course_id, documents_searchable = _document_course_filter(
        courses_dir=store.courses_dir, course=parameters.course
    )
    documents = (
        _document_results(
            store=store,
            path=path,
            query=DocumentSearchQuery(
                match=match,
                course_id=document_course_id,
                limit=SEARCH_DOCUMENT_RESULTS_LIMIT,
                offset=0,
            ),
            raw_query=parameters.q,
        )
        if documents_searchable
        else ([], 0)
    )
    return _search_response(
        store=store, results=results, parameters=parameters, documents=documents
    )

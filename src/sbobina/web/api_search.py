from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field

from sbobina.courses import effective_course
from sbobina.search_text import build_match_query
from sbobina.web import search_service
from sbobina.web.job_store import JobStore
from sbobina.web.lecture_title import reader_title
from sbobina.web.search_index import SearchHit
from sbobina.web.search_service import LectureResult, LectureResults, SearchQuery

router = APIRouter(prefix="/api/v1")

SEARCH_COURSE_JOB_LIMIT = 100_000
SEARCH_PASSAGES_PER_LECTURE = 3


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


def _search_response(
    store: JobStore, results: LectureResults, parameters: SearchParameters
) -> dict[str, Any]:
    total = results.total
    return {
        "data": [
            _lecture_payload(store=store, result=result) for result in results.items
        ],
        "meta": {
            "page": parameters.page,
            "per_page": parameters.per_page,
            "total": total,
            "total_pages": (total + parameters.per_page - 1) // parameters.per_page,
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
    results = search_service.search_lectures(
        store=store,
        path=request.app.state.search_index_path,
        query=SearchQuery(
            match=match,
            job_ids=_course_job_ids(store=store, course=parameters.course),
            limit=parameters.per_page,
            offset=(parameters.page - 1) * parameters.per_page,
        ),
        passages_per_lecture=SEARCH_PASSAGES_PER_LECTURE,
    )
    return _search_response(store=store, results=results, parameters=parameters)

from typing import Annotated, Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from pydantic import JsonValue
from pydantic import ValidationError as PydanticValidationError

from sbobina.courses import CourseLecture, group_courses
from sbobina.web.job_models import LectureMeta
from sbobina.web.job_store import JobStore

router = APIRouter(prefix="/api/v1")


def _parse_meta(body: JsonValue) -> LectureMeta:
    try:
        return LectureMeta.model_validate(body)
    except PydanticValidationError as error:
        details = [
            {
                "type": detail["type"],
                "loc": ("course",),
                "msg": str(
                    detail.get("ctx", {}).get(
                        "error", "Specifica il corso come testo o null"
                    )
                ),
            }
            for detail in error.errors()
        ]
        raise RequestValidationError(errors=details) from error


@router.get("/courses")
def list_courses(
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1)] = 20,
) -> dict[str, Any]:
    store: JobStore = request.app.state.job_store
    courses = group_courses(
        records=(
            CourseLecture(
                course=store.read_meta(job_id=str(record.id)).course,
                subject=record.config.subject,
                created_at=record.created_at,
            )
            for record in store.iter_records()
        )
    )
    total = len(courses)
    start = (page - 1) * per_page
    return {
        "data": [
            jsonable_encoder(course) for course in courses[start : start + per_page]
        ],
        "meta": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": (total + per_page - 1) // per_page,
        },
    }


@router.patch("/jobs/{job_id}/meta")
def update_meta(
    job_id: str, body: Annotated[JsonValue, Body()], request: Request
) -> dict[str, Any]:
    store: JobStore = request.app.state.job_store
    meta = store.write_meta(job_id=job_id, meta=_parse_meta(body=body))
    return {"data": meta.model_dump(mode="json")}

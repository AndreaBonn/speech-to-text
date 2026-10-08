from functools import partial
from typing import Annotated, Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, JsonValue, field_validator
from pydantic import ValidationError as PydanticValidationError

from sbobina.course_registry import (
    REGISTRY_LOCK,
    CourseExistsError,
    iter_courses,
    rename_key,
)
from sbobina.courses import (
    CourseLecture,
    CourseSummary,
    course_key,
    effective_course,
    group_courses,
    normalize_course_label,
)
from sbobina.web.errors import ConflictError, NotFoundError
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
                # An empty loc means the body itself is not an object.
                "loc": detail["loc"] or ("body",),
                "msg": str(
                    detail.get("ctx", {}).get(
                        "error", "Specifica il corso come testo o null"
                    )
                ),
            }
            for detail in error.errors()
        ]
        raise RequestValidationError(errors=details) from error


def _collect_courses(store: JobStore) -> list[CourseSummary]:
    return group_courses(
        records=(
            CourseLecture(
                course=store.read_meta(job_id=str(record.id)).course,
                subject=record.config.subject,
                created_at=record.created_at,
            )
            for record in store.iter_records()
        ),
        registered=(
            CourseSummary(
                key=course.key,
                label=course.label,
                lecture_count=0,
                last_lecture_at=course.created_at,
            )
            for course in iter_courses(courses_dir=store.courses_dir)
        ),
    )


def course_labels(store: JobStore) -> list[str]:
    """Labels of every known course, for the suggestions of a course field."""
    return [course.label for course in _collect_courses(store=store)]


def course_label(store: JobStore, key: str) -> str | None:
    """Label the lectures and registry already give the course with this key."""
    return next(
        (course.label for course in _collect_courses(store=store) if course.key == key),
        None,
    )


@router.get("/courses")
def list_courses(
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1)] = 20,
) -> dict[str, Any]:
    courses = _collect_courses(store=request.app.state.job_store)
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


@router.get("/jobs/{job_id}/meta")
def get_meta(job_id: str, request: Request) -> dict[str, Any]:
    store: JobStore = request.app.state.job_store
    meta = store.read_meta(job_id=job_id)
    return {"data": meta.model_dump(mode="json")}


class RenameCourseRequest(BaseModel):
    label: str

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        normalized = normalize_course_label(raw=value)
        if normalized is None:
            raise ValueError("Specifica il nome del corso")
        return normalized


def _rename_lectures(old: str, label: str, store: JobStore) -> None:
    for record in store.iter_records():
        meta = store.read_meta(job_id=str(record.id))
        effective = effective_course(course=meta.course, subject=record.config.subject)
        if course_key(label=effective) == old:
            store.write_meta(job_id=str(record.id), meta=LectureMeta(course=label))


def _require_course(store: JobStore, key: str) -> None:
    if not any(item.key == key for item in _collect_courses(store)):
        raise NotFoundError(entity="Corso", id=key)


@router.post("/courses/{key:path}/rename")
def rename_course(
    key: str, body: RenameCourseRequest, request: Request
) -> dict[str, Any]:
    store: JobStore = request.app.state.job_store
    if not course_key(label=key):
        raise ConflictError(message="Seleziona un corso", code="COURSE_REQUIRED")
    directory = store.courses_dir
    try:
        with REGISTRY_LOCK:
            _require_course(store=store, key=key)
            record = rename_key(
                courses_dir=directory,
                old=key,
                new=body.label,
                update_lectures=partial(_rename_lectures, store=store),
            )
    except CourseExistsError as error:
        raise ConflictError(
            message="Il corso di destinazione esiste già",
            code=error.code,
        ) from error
    return {"data": jsonable_encoder(record)}


@router.patch("/jobs/{job_id}/meta")
def update_meta(
    job_id: str, body: Annotated[JsonValue, Body()], request: Request
) -> dict[str, Any]:
    store: JobStore = request.app.state.job_store
    meta = store.write_meta(job_id=job_id, meta=_parse_meta(body=body))
    return {"data": meta.model_dump(mode="json")}

import logging
from dataclasses import asdict, dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from sbobina.exam_cues import ExamCue, find_exam_cues
from sbobina.models import load_transcript
from sbobina.web.api_files import TRANSCRIPT_FILES
from sbobina.web.course_retrieval import NO_REGISTERED_COURSE, course_scope
from sbobina.web.errors import NotFoundError, ValidationError
from sbobina.web.job_store import JobStore
from sbobina.web.search_schema import Variant
from sbobina.web.search_service import PREFERRED_VARIANTS

router = APIRouter(prefix="/api/v1/courses")
logger = logging.getLogger(__name__)
DEFAULT_PAGE = 1
DEFAULT_PER_PAGE = 20
ALL_LEVELS = "all"
STRONG_LEVEL = "strong"
ACCEPTED_LEVELS = (STRONG_LEVEL, ALL_LEVELS)


@dataclass(frozen=True)
class CueQuery:
    level: str
    page: int
    per_page: int


def _query(
    level: str = ALL_LEVELS,
    page: Annotated[int, Query(ge=1)] = DEFAULT_PAGE,
    per_page: Annotated[int, Query(ge=1)] = DEFAULT_PER_PAGE,
) -> CueQuery:
    if level not in ACCEPTED_LEVELS:
        raise ValidationError(message="Il parametro level deve essere strong o all")
    return CueQuery(level=level, page=page, per_page=per_page)


def _services(request: Request) -> JobStore:
    store: JobStore = request.app.state.job_store
    return store


Services = Annotated[JobStore, Depends(_services)]
QueryOptions = Annotated[CueQuery, Depends(_query)]


@dataclass(frozen=True)
class LectureCue:
    cue: ExamCue
    variant: Variant


def _cues_for_job(store: JobStore, job_id: str) -> tuple[LectureCue, ...]:
    directory = store.jobs_dir / job_id
    for variant in PREFERRED_VARIANTS:
        path = directory / TRANSCRIPT_FILES[variant]
        if not path.exists():
            continue
        try:
            transcript = load_transcript(path=path)
            cues = find_exam_cues(transcript=transcript, job_id=job_id)
        except (OSError, ValueError, KeyError, TypeError) as error:
            logger.warning("Unreadable transcript, skipping %s: %s", path, error)
            return ()
        # The reader must open the variant the quote was read from.
        return tuple(LectureCue(cue=cue, variant=variant) for cue in cues)
    return ()


def _cue_payload(item: LectureCue) -> dict[str, Any]:
    cue = item.cue
    href = f"/lettore/{cue.job_id}?t={cue.start}&variant={item.variant}"
    return {**asdict(cue), "href": href}


@router.get("/{key:path}/exam-cues")
def list_exam_cues(key: str, services: Services, query: QueryOptions) -> dict[str, Any]:
    scope = course_scope(store=services, key=key)
    if scope.course_id == NO_REGISTERED_COURSE and not scope.job_ids:
        raise NotFoundError(entity="Corso", id=key)
    cues = [
        item
        for job_id in sorted(scope.job_ids)
        for item in _cues_for_job(store=services, job_id=job_id)
        if query.level == ALL_LEVELS or item.cue.level == STRONG_LEVEL
    ]
    total = len(cues)
    start = (query.page - 1) * query.per_page
    return {
        "data": [
            _cue_payload(item=item) for item in cues[start : start + query.per_page]
        ],
        "meta": {
            "page": query.page,
            "per_page": query.per_page,
            "total": total,
            "total_pages": (total + query.per_page - 1) // query.per_page,
        },
    }

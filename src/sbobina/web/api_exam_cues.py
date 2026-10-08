import logging
from dataclasses import asdict, dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import TypeAdapter

from sbobina.exam_cues import ExamCue, find_exam_cues
from sbobina.models import Transcript
from sbobina.web.api_files import TRANSCRIPT_FILES, transcript_revision
from sbobina.web.course_retrieval import (
    NO_REGISTERED_COURSE,
    course_scope,
)
from sbobina.web.errors import NotFoundError, ValidationError
from sbobina.web.job_models import JobStatus
from sbobina.web.job_store import JobStore
from sbobina.web.search_schema import Variant
from sbobina.web.search_service import PREFERRED_VARIANTS

router = APIRouter(prefix="/api/v1/courses")
# Type-checked parse, like card_anchors/api_study: a word with "text": null is
# a corrupted lecture (unavailable), not a 500 for the whole course.
TRANSCRIPT_ADAPTER = TypeAdapter(Transcript)
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
    revision: str


@dataclass(frozen=True)
class JobCuesResult:
    cues: tuple[LectureCue, ...]
    unavailable: bool


def _cues_for_job(store: JobStore, job_id: str) -> JobCuesResult:
    directory = store.jobs_dir / job_id
    for variant in PREFERRED_VARIANTS:
        path = directory / TRANSCRIPT_FILES[variant]
        if not path.exists():
            continue
        try:
            # One read per lecture: cues and revision come from the same text,
            # so a card anchored with this revision quotes this exact version.
            content = path.read_text(encoding="utf-8")
            transcript = TRANSCRIPT_ADAPTER.validate_json(content)
            cues = find_exam_cues(transcript=transcript, job_id=job_id)
        except (OSError, ValueError) as error:
            logger.warning("Unreadable transcript, skipping %s: %s", path, error)
            return JobCuesResult(cues=(), unavailable=True)
        revision = transcript_revision(content=content)
        # The reader must open the variant the quote was read from.
        return JobCuesResult(
            cues=tuple(
                LectureCue(cue=cue, variant=variant, revision=revision) for cue in cues
            ),
            unavailable=False,
        )
    return JobCuesResult(cues=(), unavailable=False)


def _cue_payload(item: LectureCue) -> dict[str, Any]:
    cue = item.cue
    href = f"/lettore/{cue.job_id}?t={cue.start}&variant={item.variant}"
    return {**asdict(cue), "href": href, "revision": item.revision}


@router.get("/{key:path}/exam-cues")
def list_exam_cues(key: str, services: Services, query: QueryOptions) -> dict[str, Any]:
    scope = course_scope(store=services, key=key)
    if scope.course_id == NO_REGISTERED_COURSE and not scope.job_ids:
        raise NotFoundError(entity="Corso", id=key)
    # Only DONE jobs: a job interrupted after the transcript was already
    # written (recover_record, work_items.py) still has a readable file on
    # disk, and its stale cues must not surface alongside a finished lecture.
    done = {
        str(record.id)
        for record in services.iter_records()
        if record.status == JobStatus.DONE
    }
    done_job_ids = sorted(scope.job_ids & done)
    results = [
        (job_id, _cues_for_job(store=services, job_id=job_id))
        for job_id in done_job_ids
    ]
    cues = [
        item
        for _, result in results
        for item in result.cues
        if query.level == ALL_LEVELS or item.cue.level == STRONG_LEVEL
    ]
    unavailable_jobs = [job_id for job_id, result in results if result.unavailable]
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
            "unavailable_jobs": unavailable_jobs,
        },
    }

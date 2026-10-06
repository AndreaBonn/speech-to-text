"""Page route for one practice attempt; split out of pages.py (300-line cap)."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from sbobina.course_registry import find_by_key
from sbobina.courses import course_key
from sbobina.web.errors import AttemptUnreadableError, NotFoundError
from sbobina.web.job_store import JobStore
from sbobina.web.pages import JobStoreDep, render_page
from sbobina.web.practice_store import load_attempt

router = APIRouter()


def _render_missing_attempt(
    request: Request, store: JobStore, key: str, damaged: bool = False
) -> HTMLResponse:
    return render_page(
        request=request,
        template_name="esercitazione.html",
        active="corsi",
        store=store,
        status_code=503 if damaged else 404,
        page_title="Esercitazione",
        not_found=True,
        damaged=damaged,
        course_key=key,
    )


@router.get("/corsi/{key:path}/esercitazioni/{attempt_id}", response_class=HTMLResponse)
def esercitazione(
    request: Request, store: JobStoreDep, key: str, attempt_id: str
) -> HTMLResponse:
    """One practice attempt; questions, grading and citations load client-side."""
    courses_dir = store.courses_dir
    course = find_by_key(courses_dir=courses_dir, key=course_key(label=key))
    attempt = None
    if course is not None:
        try:
            attempt = load_attempt(
                courses_dir=courses_dir, course_id=course.id, attempt_id=attempt_id
            )
        except NotFoundError:
            attempt = None
        except AttemptUnreadableError:
            return _render_missing_attempt(
                request=request, store=store, key=key, damaged=True
            )
    if course is None or attempt is None or attempt.course_id != course.id:
        return _render_missing_attempt(request=request, store=store, key=key)
    return render_page(
        request=request,
        template_name="esercitazione.html",
        active="corsi",
        store=store,
        page_title="Esercitazione",
        not_found=False,
        course_key=key,
        course_label=course.label,
        attempt_id=attempt_id,
        generation_id=attempt.generation_id,
    )

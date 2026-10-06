"""Page route for one generation, the target of a card made from it (F51)."""

import logging
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from sbobina.course_registry import find_by_key
from sbobina.courses import course_key
from sbobina.generation_models import GenerationRecord
from sbobina.web.errors import NotFoundError
from sbobina.web.generation_store import load_generation
from sbobina.web.job_store import JobStore
from sbobina.web.pages import JobStoreDep, render_page

router = APIRouter()
logger = logging.getLogger("sbobina")


def _find_generation(
    store: JobStore, course_id: str, gen_id: str
) -> GenerationRecord | None:
    try:
        UUID(gen_id)
    except ValueError:
        return None
    try:
        return load_generation(
            courses_dir=store.courses_dir, course_id=course_id, gen_id=gen_id
        )
    except NotFoundError:
        return None
    except ValueError as error:
        # A corrupted record answers 404 like a missing one, but leaves a trace.
        logger.warning("Generazione %s non leggibile: %s", gen_id, error)
        return None


@router.get("/corsi/{key:path}/generazioni/{gen_id}", response_class=HTMLResponse)
def generazione(
    request: Request, store: JobStoreDep, key: str, gen_id: str
) -> HTMLResponse:
    """One generation; its questions or sections load client-side."""
    course = find_by_key(courses_dir=store.courses_dir, key=course_key(label=key))
    record = (
        None
        if course is None
        else _find_generation(store=store, course_id=course.id, gen_id=gen_id)
    )
    return render_page(
        request=request,
        template_name="generazione.html",
        active="corsi",
        store=store,
        status_code=200 if record is not None else 404,
        page_title="Generazione",
        not_found=record is None,
        course_key=key,
        course_label=course.label if course is not None else key,
        generation_id=gen_id,
        topic=record.topic if record is not None else "",
    )

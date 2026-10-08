from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import JsonValue

from sbobina.course_registry import find_by_key
from sbobina.courses import MAX_COURSE_LABEL_LENGTH, course_key, effective_course
from sbobina.document_models import CourseDocument
from sbobina.model_catalog import ollama_options, whisper_options
from sbobina.web.api_courses import course_labels
from sbobina.web.document_store import read_document
from sbobina.web.errors import NotFoundError
from sbobina.web.job_models import JobRecord
from sbobina.web.job_store import JobStore
from sbobina.web.lecture_title import reader_title as _reader_title
from sbobina.web.model_service import list_whisper_models, ollama_status
from sbobina.web.pages_nav import build_nav, course_breadcrumbs, reader_nav_id

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _job_store(request: Request) -> JobStore:
    store: JobStore = request.app.state.job_store
    return store


JobStoreDep = Annotated[JobStore, Depends(_job_store)]


def _render(
    request: Request,
    template_name: str,
    active: str,
    store: JobStore,
    status_code: int = 200,
    **context: Any,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        status_code=status_code,
        context={"nav_items": build_nav(active=active, store=store), **context},
    )


# Public name for page routes split into their own modules (300-line cap).
render_page = _render


def _installed_ollama_models(
    status: dict[str, JsonValue],
) -> list[dict[str, JsonValue]]:
    models = status["models"]
    if not isinstance(models, list):
        return []
    return [model for model in models if isinstance(model, dict)]


@router.get("/", response_class=HTMLResponse)
def index(request: Request, store: JobStoreDep) -> HTMLResponse:
    """Upload form plus the live queue of queued and running jobs."""
    settings = request.app.state.settings
    ollama = ollama_status(host=settings.ollama_host)
    defaults = {
        "correct": False,
        "ollama_model": settings.ollama_model,
        "subject": "",
        "whisper_model": "auto",
        "beam_size": settings.beam_size,
        "vad_filter": settings.vad_filter,
        "condition_on_previous_text": settings.condition_on_previous_text,
        "uncertain_threshold": settings.uncertain_threshold,
    }
    return _render(
        request=request,
        template_name="index.html",
        active="nuova",
        store=store,
        page_title="Nuova trascrizione",
        defaults=defaults,
        whisper_options=whisper_options(
            models=list_whisper_models(settings=settings),
            gpu_model=settings.whisper_model_gpu,
            cpu_model=settings.whisper_model_cpu,
        ),
        ollama_options=ollama_options(
            installed=_installed_ollama_models(status=ollama),
            default_model=settings.ollama_model,
            is_ready=ollama["status"] == "ready",
        ),
        ollama_message=None if ollama["status"] == "ready" else ollama["message"],
        course_labels=course_labels(store=store),
    )


@router.get("/corsi", response_class=HTMLResponse)
def corsi(request: Request, store: JobStoreDep) -> HTMLResponse:
    """Courses overview; the list and each course's lectures are fetched client-side."""
    return _render(
        request=request,
        template_name="corsi.html",
        active="corsi",
        store=store,
        page_title="Corsi",
    )


@router.get("/ripasso", response_class=HTMLResponse)
def ripasso(request: Request, store: JobStoreDep) -> HTMLResponse:
    """Spaced-repetition queue; the per-course summary and session load client-side."""
    return _render(
        request=request,
        template_name="ripasso.html",
        active="ripasso",
        store=store,
        page_title="Ripasso",
    )


@router.get("/storico", response_class=HTMLResponse)
def storico(request: Request, store: JobStoreDep) -> HTMLResponse:
    """Paginated job history; the table itself is fetched client-side."""
    return _render(
        request=request,
        template_name="storico.html",
        active="storico",
        store=store,
        page_title="Storico",
    )


@router.get("/modelli", response_class=HTMLResponse)
def modelli(request: Request, store: JobStoreDep) -> HTMLResponse:
    """Whisper and Ollama model catalogue; fetched and downloaded client-side."""
    return _render(
        request=request,
        template_name="modelli.html",
        active="modelli",
        store=store,
        page_title="Modelli",
    )


@router.get("/impostazioni", response_class=HTMLResponse)
def impostazioni(request: Request, store: JobStoreDep) -> HTMLResponse:
    """Settings page: engine, model chain, API keys, transcription engine."""
    return _render(
        request=request,
        template_name="impostazioni.html",
        active="impostazioni",
        store=store,
        page_title="Impostazioni",
    )


@router.get("/confronto", response_class=HTMLResponse)
def confronto(request: Request, store: JobStoreDep) -> HTMLResponse:
    """WER comparison form; the computation happens client-side via the API."""
    return _render(
        request=request,
        template_name="confronto.html",
        active="confronto",
        store=store,
        page_title="Confronto (WER)",
    )


@router.get("/lettore/{job_id}", response_class=HTMLResponse)
def lettore(request: Request, store: JobStoreDep, job_id: str) -> HTMLResponse:
    """Synchronised reader; transcript, audio and re-listen points load client-side."""
    try:
        record = store.get(job_id=job_id)
    except NotFoundError:
        return _render(
            request=request,
            template_name="reader.html",
            active="lettore",
            store=store,
            status_code=404,
            page_title="Lettore",
            not_found=True,
            job_id=job_id,
        )
    course = _reader_course(store=store, record=record)
    return _render(
        request=request,
        template_name="reader.html",
        active=reader_nav_id(store=store, job_id=job_id),
        store=store,
        page_title="Lettore",
        not_found=False,
        job_id=job_id,
        has_audio=not record.imported,
        title=_reader_title(record),
        created_at=record.created_at.strftime("%d/%m/%Y"),
        course=course,
        breadcrumbs=_course_path(course=course),
        course_max_length=MAX_COURSE_LABEL_LENGTH,
        subject=record.config.subject or "",
    )


def _course_path(course: str) -> list[dict[str, str]]:
    """Corsi › <course> above a lecture page, or no path for a lecture without one."""
    if not course:
        return []
    return course_breadcrumbs(key=course_key(label=course), label=course)


def _reader_course(store: JobStore, record: JobRecord) -> str:
    """The course shown in the reader field: the user's choice, else the subject."""
    meta = store.read_meta(job_id=str(record.id))
    return effective_course(course=meta.course, subject=record.config.subject) or ""


@router.get("/studio/{job_id}", response_class=HTMLResponse)
def studio(request: Request, store: JobStoreDep, job_id: str) -> HTMLResponse:
    """Study notes of one lecture; the material itself loads client-side."""
    try:
        record = store.get(job_id=job_id)
    except NotFoundError:
        return _render(
            request=request,
            template_name="reader.html",
            active="lettore",
            store=store,
            status_code=404,
            page_title="Materiali di studio",
            not_found=True,
            job_id=job_id,
        )
    return _render(
        request=request,
        template_name="studio.html",
        active=reader_nav_id(store=store, job_id=job_id),
        store=store,
        page_title="Materiali di studio",
        job_id=job_id,
        title=_reader_title(record),
        breadcrumbs=[
            *_course_path(course=_reader_course(store=store, record=record)),
            {"label": _reader_title(record), "href": f"/lettore/{job_id}"},
        ],
    )


def _render_missing_doc(request: Request, store: JobStore, key: str) -> HTMLResponse:
    return _render(
        request=request,
        template_name="documento.html",
        active="corsi",
        store=store,
        status_code=404,
        page_title="Documento",
        not_found=True,
        course_key=key,
    )


@router.get("/corsi/{key:path}/documenti/{doc_id}", response_class=HTMLResponse)
def documento(
    request: Request, store: JobStoreDep, key: str, doc_id: str
) -> HTMLResponse:
    """One course document's reading page; its pages of text load client-side."""
    courses_dir = store.courses_dir
    course = find_by_key(courses_dir=courses_dir, key=course_key(label=key))
    document: CourseDocument | None = None
    if course is not None:
        try:
            document = read_document(
                courses_dir=courses_dir, course_id=course.id, doc_id=doc_id
            )
        except NotFoundError:
            document = None
    if course is None or document is None:
        return _render_missing_doc(request=request, store=store, key=key)
    return _render(
        request=request,
        template_name="documento.html",
        active="corsi",
        store=store,
        page_title="Materiale del corso",
        not_found=False,
        course_key=key,
        course_label=course.label,
        breadcrumbs=course_breadcrumbs(key=key, label=course.label),
        doc_id=doc_id,
        filename=document.filename,
    )

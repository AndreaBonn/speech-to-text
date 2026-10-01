from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from faster_whisper.utils import available_models

from sbobina.web.errors import NotFoundError
from sbobina.web.job_models import JobRecord, JobStatus
from sbobina.web.job_store import JobStore

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# How many recent jobs to scan for the rail's "Lettore" destination. A local
# install rarely has more queued than this between two completed lectures.
READER_LOOKUP_PAGE_SIZE = 50


@dataclass(frozen=True)
class NavSpec:
    id: str
    label: str
    href: str | None  # None: resolved per-request (the Lettore destination).


NAV_SPECS = (
    NavSpec(id="nuova", label="Nuova trascrizione", href="/"),
    NavSpec(id="lettore", label="Lettore", href=None),
    NavSpec(id="storico", label="Storico", href="/storico"),
    NavSpec(id="modelli", label="Modelli", href="/modelli"),
    NavSpec(id="confronto", label="Confronto (WER)", href="/confronto"),
)


def _job_store(request: Request) -> JobStore:
    store: JobStore = request.app.state.job_store
    return store


JobStoreDep = Annotated[JobStore, Depends(_job_store)]


def _last_reader_href(store: JobStore) -> str | None:
    """Most recent completed job, so the rail can link straight to it.

    The reader (T022) is not built yet, but the destination already resolves
    to a real job once one exists, instead of staying disabled forever.
    """
    page = store.list(page=1, per_page=READER_LOOKUP_PAGE_SIZE)
    for record in page.items:
        if record.status == JobStatus.DONE:
            return f"/lettore/{record.id}"
    return None


def _nav(active: str, store: JobStore) -> list[dict[str, Any]]:
    reader_href = _last_reader_href(store=store)
    items = []
    for spec in NAV_SPECS:
        href = reader_href if spec.id == "lettore" else spec.href
        items.append(
            {
                "id": spec.id,
                "label": spec.label,
                "href": href,
                "disabled": href is None,
                "active": spec.id == active,
            }
        )
    return items


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
        context={"nav_items": _nav(active=active, store=store), **context},
    )


def _reader_title(record: JobRecord) -> str:
    """Source file name first, then the subject, then a dated fallback.

    Mirrors ``jobTitle()`` in jobs.js so the queue row and the reader page
    never disagree on what to call the same job.
    """
    if record.source_name:
        return record.source_name
    if record.config.subject:
        return record.config.subject
    return f"Lezione del {record.created_at.strftime('%d/%m/%Y')}"


@router.get("/", response_class=HTMLResponse)
def index(request: Request, store: JobStoreDep) -> HTMLResponse:
    """Upload form plus the live queue of queued and running jobs."""
    settings = request.app.state.settings
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
        whisper_models=available_models(),
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
    """Synchronised reader: word-level transcript plus a sticky audio bar.

    The page itself only needs to know the job exists; the transcript, the
    audio and the re-listen points are fetched client-side by reader.js.
    """
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
    return _render(
        request=request,
        template_name="reader.html",
        active="lettore",
        store=store,
        page_title="Lettore",
        not_found=False,
        job_id=job_id,
        title=_reader_title(record),
        created_at=record.created_at.strftime("%d/%m/%Y"),
    )

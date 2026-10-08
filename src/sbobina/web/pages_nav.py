"""Rail navigation: the specs, the Lettore destination lookup, and the context builder."""

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from sbobina.web.job_models import JobRecord, JobStatus
from sbobina.web.job_store import JobStore
from sbobina.web.lecture_title import reader_title

# How many recent jobs to scan for the rail's "Lettore" destination. A local
# install rarely has more queued than this between two completed lectures.
READER_LOOKUP_PAGE_SIZE = 50


MAIN_GROUP = "main"
TOOLS_GROUP = "tools"


@dataclass(frozen=True)
class NavSpec:
    id: str
    label: str
    href: str | None  # None: resolved per-request (the last lecture).
    group: str = MAIN_GROUP


# S5: the technical pages sit in their own group at the foot of the rail, so
# the daily destinations (courses, review) are not on a par with them.
NAV_SPECS = (
    NavSpec(id="nuova", label="Nuova trascrizione", href="/"),
    NavSpec(id="corsi", label="Corsi", href="/corsi"),
    NavSpec(id="ripasso", label="Ripasso", href="/ripasso"),
    NavSpec(id="lettore", label="Ultima lezione", href=None),
    NavSpec(id="storico", label="Storico", href="/storico"),
    NavSpec(id="modelli", label="Modelli", href="/modelli", group=TOOLS_GROUP),
    NavSpec(
        id="confronto", label="Confronto (WER)", href="/confronto", group=TOOLS_GROUP
    ),
    NavSpec(
        id="impostazioni", label="Impostazioni", href="/impostazioni", group=TOOLS_GROUP
    ),
)


def _last_done_job(store: JobStore) -> JobRecord | None:
    """Most recent completed job: the rail names it and links straight to it."""
    page = store.list(page=1, per_page=READER_LOOKUP_PAGE_SIZE)
    for record in page.items:
        if record.status == JobStatus.DONE:
            return record
    return None


def build_nav(active: str, store: JobStore) -> list[dict[str, Any]]:
    last = _last_done_job(store=store)
    items = []
    for spec in NAV_SPECS:
        href, detail = spec.href, None
        if spec.id == "lettore" and last is not None:
            # R6: the entry names the lecture it opens, not a page type.
            href, detail = f"/lettore/{last.id}", reader_title(record=last)
        items.append(
            {
                "id": spec.id,
                "label": spec.label,
                "detail": detail,
                "href": href,
                "group": spec.group,
                "disabled": href is None,
                "active": spec.id == active,
            }
        )
    return items


def course_breadcrumbs(key: str, label: str) -> list[dict[str, str]]:
    """Corsi › <course>: the path shown above pages that belong to one course."""
    return [
        {"label": "Corsi", "href": "/corsi"},
        {"label": label, "href": f"/corsi?corso={quote(key, safe='')}"},
    ]

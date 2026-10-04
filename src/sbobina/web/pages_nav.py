"""Rail navigation: the specs, the Lettore destination lookup, and the context builder."""

from dataclasses import dataclass
from typing import Any

from sbobina.web.job_models import JobStatus
from sbobina.web.job_store import JobStore

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
    NavSpec(id="corsi", label="Corsi", href="/corsi"),
    NavSpec(id="ripasso", label="Ripasso", href="/ripasso"),
    NavSpec(id="lettore", label="Lettore", href=None),
    NavSpec(id="storico", label="Storico", href="/storico"),
    NavSpec(id="modelli", label="Modelli", href="/modelli"),
    NavSpec(id="confronto", label="Confronto (WER)", href="/confronto"),
)


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


def build_nav(active: str, store: JobStore) -> list[dict[str, Any]]:
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

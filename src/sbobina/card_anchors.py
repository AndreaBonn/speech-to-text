import logging
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

from pydantic import TypeAdapter

from sbobina.card_models import Anchor, DocumentAnchor, GenerationAnchor, LectureAnchor
from sbobina.file_cache import read_parsed
from sbobina.models import Transcript
from sbobina.study_citations import locate_quote
from sbobina.study_models import Rejection
from sbobina.web.api_files import TRANSCRIPT_FILES, transcript_revision
from sbobina.web.document_store import read_document
from sbobina.web.errors import GenerationUnreadableError, NotFoundError
from sbobina.web.generation_store import load_generation
from sbobina.web.job_store import JobStore
from sbobina.web.search_service import PREFERRED_VARIANTS

logger = logging.getLogger(__name__)
TRANSCRIPT_ADAPTER = TypeAdapter(Transcript)
type AnchorStatus = Literal[
    "ok", "moved", "source_modified", "source_removed", "unavailable"
]


@dataclass(frozen=True, kw_only=True)
class AnchorResolution:
    href: str
    status: AnchorStatus


def resolve_lecture(
    anchor: LectureAnchor, transcript: Transcript, revision: str, variant: str
) -> AnchorResolution:
    """Resolve the current lecture location without I/O.

    Parameters
    ----------
    anchor : LectureAnchor
        Saved revision, segment and quotation.
    transcript : Transcript
        Current immutable transcript.
    revision : str
        Fingerprint of the exact content parsed into the transcript.
    variant : str
        Reader variant of that content.
    """
    href = f"/lettore/{anchor.job_id}"
    segments = transcript.segments
    if anchor.revision == revision and anchor.segment_index < len(segments):
        start = segments[anchor.segment_index].start
        return AnchorResolution(href=f"{href}?t={start}&variant={variant}", status="ok")
    return _relocate(anchor=anchor, transcript=transcript, variant=variant)


def _relocate(
    anchor: LectureAnchor, transcript: Transcript, variant: str
) -> AnchorResolution:
    href = f"/lettore/{anchor.job_id}"
    segments = transcript.segments
    allowed = frozenset(range(len(segments)))
    candidates = (anchor.segment_index, *sorted(allowed - {anchor.segment_index}))
    for index in candidates:
        match = locate_quote(
            segments=segments,
            segment_index=index,
            quote=anchor.quote,
            allowed=allowed.intersection((index, index + 1)),
        )
        if not isinstance(match, Rejection):
            return AnchorResolution(
                href=f"{href}?t={match.timestamp}&variant={variant}", status="moved"
            )
    return AnchorResolution(href=f"{href}?variant={variant}", status="source_modified")


def _transcript_and_revision(content: str) -> tuple[Transcript, str]:
    # Hash the same bytes we parse so an intervening edit cannot mix revisions.
    return TRANSCRIPT_ADAPTER.validate_json(content), transcript_revision(
        content=content
    )


def _lecture_resolution(anchor: LectureAnchor, store: JobStore) -> AnchorResolution:
    href = f"/lettore/{anchor.job_id}"
    try:
        record = store.get(job_id=anchor.job_id)
    except NotFoundError as error:
        logger.warning("Lecture source removed %s: %s", anchor.job_id, error)
        return AnchorResolution(href=href, status="source_removed")
    directory = store.jobs_dir / str(record.id)
    try:
        for variant in PREFERRED_VARIANTS:
            path = directory / TRANSCRIPT_FILES[variant]
            if not path.exists():
                continue
            transcript, revision = read_parsed(
                path=path, parse=_transcript_and_revision
            )
            return resolve_lecture(
                anchor=anchor, transcript=transcript, revision=revision, variant=variant
            )
    except (OSError, ValueError) as error:
        logger.warning("Unreadable lecture source %s: %s", anchor.job_id, error)
        return AnchorResolution(href=href, status="unavailable")
    return AnchorResolution(href=href, status="source_removed")


def _document_resolution(
    anchor: DocumentAnchor, store: JobStore, course_id: str, key: str
) -> AnchorResolution:
    href = (
        f"/corsi/{quote(string=key, safe='')}/documenti/{anchor.doc_id}?p={anchor.page}"
    )
    try:
        document = read_document(
            courses_dir=store.courses_dir, course_id=course_id, doc_id=anchor.doc_id
        )
    except NotFoundError:
        return AnchorResolution(href=href, status="source_removed")
    except (OSError, ValueError) as error:
        logger.warning("Unreadable document source %s: %s", anchor.doc_id, error)
        return AnchorResolution(href=href, status="unavailable")
    return revision_resolution(href=href, unchanged=document.sha256 == anchor.sha256)


def revision_resolution(href: str, unchanged: bool) -> AnchorResolution:
    return AnchorResolution(href=href, status="ok" if unchanged else "source_modified")


def _generation_resolution(
    anchor: GenerationAnchor, store: JobStore, course_id: str, key: str
) -> AnchorResolution:
    href = f"/corsi/{quote(string=key, safe='')}/generazioni/{anchor.generation_id}"
    try:
        load_generation(
            courses_dir=store.courses_dir,
            course_id=course_id,
            gen_id=anchor.generation_id,
        )
    except NotFoundError:
        return AnchorResolution(href=href, status="source_removed")
    except (OSError, GenerationUnreadableError) as error:
        logger.warning(
            "Unreadable generation source %s: %s", anchor.generation_id, error
        )
        return AnchorResolution(href=href, status="unavailable")
    return AnchorResolution(href=href, status="ok")


def resolve_anchor(
    anchor: Anchor, store: JobStore, course_id: str, key: str
) -> AnchorResolution:
    if isinstance(anchor, LectureAnchor):
        return _lecture_resolution(anchor=anchor, store=store)
    if isinstance(anchor, DocumentAnchor):
        return _document_resolution(
            anchor=anchor, store=store, course_id=course_id, key=key
        )
    return _generation_resolution(
        anchor=anchor, store=store, course_id=course_id, key=key
    )

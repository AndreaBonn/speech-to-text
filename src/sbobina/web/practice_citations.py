from typing import Any
from urllib.parse import quote

from fastapi.encoders import jsonable_encoder

from sbobina.card_anchors import AnchorResolution, resolve_anchor
from sbobina.card_models import Anchor, DocumentAnchor, LectureAnchor
from sbobina.generation_models import GenerationCitation
from sbobina.web.generation_citations_api import CitationContext, resolve_citation


def citation_anchor(
    citation: GenerationCitation, context: CitationContext
) -> Anchor | None:
    for source in context.sources:
        if (
            citation.doc_id is not None
            and source.doc_id == citation.doc_id
            and source.sha256
        ):
            assert citation.page is not None
            return DocumentAnchor(
                doc_id=citation.doc_id,
                sha256=source.sha256,
                page=citation.page,
                quote=citation.quote,
            )
        if (
            citation.job_id is not None
            and source.job_id == citation.job_id
            and source.revision
        ):
            return lecture_anchor(citation=citation, revision=source.revision)
    return None


def lecture_anchor(citation: GenerationCitation, revision: str) -> LectureAnchor | None:
    assert citation.job_id is not None
    prefix = f"L{citation.job_id}-S"
    index = citation.passage_id.removeprefix(prefix)
    if not citation.passage_id.startswith(prefix) or not index.isdecimal():
        return None
    return LectureAnchor(
        job_id=citation.job_id,
        revision=revision,
        segment_index=int(index),
        quote=citation.quote,
    )


def practice_citation(
    citation: GenerationCitation, context: CitationContext
) -> dict[str, Any]:
    anchor = citation_anchor(citation=citation, context=context)
    if anchor is not None:
        resolution = resolve_anchor(
            anchor=anchor,
            store=context.store,
            course_id=context.course_id,
            key=context.key,
        )
        if isinstance(anchor, LectureAnchor) and resolution.status == "ok":
            # A generation window may cite a later segment than its starting anchor.
            payload = resolve_citation(citation=citation, context=context)
            resolution = AnchorResolution(
                href=payload["href"] or resolution.href, status="ok"
            )
    else:
        # Legacy snapshots have no source fingerprint, so freshness is unknown.
        payload = resolve_citation(citation=citation, context=context)
        resolution = AnchorResolution(
            href=payload["href"] or fallback_href(citation=citation, key=context.key),
            status="unavailable" if payload["href"] else "source_removed",
        )
    return {**jsonable_encoder(obj=citation), **jsonable_encoder(obj=resolution)}


def fallback_href(citation: GenerationCitation, key: str) -> str:
    if citation.doc_id is not None:
        return f"/corsi/{quote(string=key, safe='')}/documenti/{citation.doc_id}?p={citation.page}"
    return f"/lettore/{citation.job_id}?t={citation.timestamp}"

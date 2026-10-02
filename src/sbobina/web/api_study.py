from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from pydantic import TypeAdapter
from starlette.responses import JSONResponse

from sbobina.models import Transcript
from sbobina.render import RenderOptions, group_paragraphs
from sbobina.study_citations import locate_quote
from sbobina.study_models import Citation, Rejection, StudyChapter, StudyItem
from sbobina.study_render import load_study
from sbobina.web.api_files import (
    TRANSCRIPT_FILES,
    existing_file,
    find_job,
    job_render_options,
    transcript_revision,
)
from sbobina.web.api_jobs import Services
from sbobina.web.responses import error_response

router = APIRouter(prefix="/api/v1/jobs")
TRANSCRIPT_ADAPTER = TypeAdapter(Transcript)
STUDY_FILE = "audio.studio.json"


@dataclass(frozen=True)
class CitationContext:
    transcript: Transcript
    paragraphs: list[int]
    reader_url: str
    variant: str


def _citation_payload(citation: Citation, context: CitationContext) -> dict[str, Any]:
    match = locate_quote(
        segments=context.transcript.segments,
        segment_index=citation.segment_index,
        quote=citation.quote,
        allowed=frozenset(range(len(context.transcript.segments))),
    )
    # load_study validated these citations against this same immutable transcript.
    assert not isinstance(match, Rejection)
    return {
        "quote": citation.quote,
        "timestamp": match.timestamp,
        "paragrafo": context.paragraphs[match.word_indices[0].segment_index],
        "href": f"{context.reader_url}?t={match.timestamp}&variant={context.variant}",
    }


def _item_payload(item: StudyItem, context: CitationContext) -> dict[str, Any]:
    payload: dict[str, Any] = jsonable_encoder(obj=item)
    payload["citations"] = [
        _citation_payload(citation=citation, context=context)
        for citation in item.citations
    ]
    return payload


def _chapter_payload(chapter: StudyChapter, context: CitationContext) -> dict[str, Any]:
    return {
        "title": chapter.title,
        "start": chapter.start,
        **{
            name: [_item_payload(item=item, context=context) for item in items]
            for name, items in (
                ("summary", chapter.summary),
                ("concepts", chapter.concepts),
                ("questions", chapter.questions),
            )
        },
    }


def _load_current_transcript(directory: Path) -> tuple[Transcript, str]:
    name = TRANSCRIPT_FILES["corrected"]
    if not (directory / name).is_file():
        name = TRANSCRIPT_FILES["original"]
    source = existing_file(directory=directory, name=name)
    content = source.read_text(encoding="utf-8")
    return TRANSCRIPT_ADAPTER.validate_json(content), transcript_revision(
        content=content
    )


def _material_payload(
    directory: Path, job_id: str, options: RenderOptions
) -> dict[str, Any]:
    transcript, revision = _load_current_transcript(directory=directory)
    loaded = load_study(path=directory / STUDY_FILE, transcript=transcript)
    result = loaded.result
    groups = group_paragraphs(segments=transcript.segments, options=options)
    context = CitationContext(
        transcript=transcript,
        paragraphs=[
            number for number, group in enumerate(groups, start=1) for _ in group
        ],
        reader_url=f"/lettore/{job_id}",
        variant=result.source_variant,
    )
    payload: dict[str, Any] = jsonable_encoder(obj=result)
    payload.update(
        chapters=[
            _chapter_payload(chapter=chapter, context=context)
            for chapter in result.chapters
        ],
        discarded={count.reason: count.count for count in result.discarded},
        stale_dropped=loaded.stale_dropped,
        stale=result.source_revision != revision,
    )
    return payload


@router.post("/{job_id}/study", status_code=202)
def queue_study(job_id: str, services: Services) -> dict[str, Any]:
    record = services.supervisor.submit_study(job_id=job_id)
    assert record.study is not None
    return {"data": {"status": record.study.status}, "meta": {}}


@router.get("/{job_id}/study", response_model=None)
def get_study(request: Request, job_id: str) -> dict[str, Any] | JSONResponse:
    record, directory = find_job(request=request, job_id=job_id)
    material = None
    if (directory / STUDY_FILE).is_file():
        material = _material_payload(
            directory=directory,
            job_id=str(record.id),
            options=job_render_options(request=request, record=record),
        )
    elif record.study is None:
        return error_response(
            code="STUDY_NOT_FOUND",
            message="Materiale di studio non ancora generato",
            status_code=404,
        )
    return {
        "data": {
            "study": record.study.model_dump(mode="json") if record.study else None,
            "material": material,
        },
        "meta": {},
    }

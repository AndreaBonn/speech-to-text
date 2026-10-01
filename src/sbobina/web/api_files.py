from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from starlette.responses import FileResponse

from sbobina.models import load_transcript
from sbobina.render import RenderOptions
from sbobina.settings import Settings
from sbobina.web.errors import NotFoundError
from sbobina.web.job_models import JobRecord
from sbobina.web.job_store import JobStore
from sbobina.web.reader import build_paragraphs, build_review_points

router = APIRouter(prefix="/api/v1/jobs")

AUDIO_MEDIA_TYPES = {
    ".wav": "audio/x-wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
    ".aac": "audio/aac",
}
FileKind = Literal["md", "json", "corrected_md", "corrected_json", "report"]
FILE_NAMES: dict[str, str] = {
    "md": "audio.md",
    "json": "audio.json",
    "corrected_md": "audio.corretto.md",
    "corrected_json": "audio.corretto.json",
    "report": "audio.correzioni.md",
}
TranscriptVariant = Literal["original", "corrected"]
TRANSCRIPT_FILES = {"original": "audio.json", "corrected": "audio.corretto.json"}


def _job(request: Request, job_id: str) -> tuple[JobRecord, Path]:
    store: JobStore = request.app.state.job_store
    record = store.get(job_id=job_id)
    return record, store.jobs_dir / str(record.id)


def _existing(directory: Path, name: str) -> Path:
    path = directory / name
    if not path.is_file():
        raise NotFoundError(entity="File", id=name)
    return path


@router.get("/{job_id}/audio")
def get_audio(request: Request, job_id: str) -> FileResponse:
    """Serve the uploaded recording; Starlette answers Range requests with 206."""
    _, directory = _job(request=request, job_id=job_id)
    candidates = [
        path
        for path in directory.glob("audio.*")
        if path.suffix.lower() in AUDIO_MEDIA_TYPES
    ]
    if not candidates:
        raise NotFoundError(entity="Audio", id=job_id)
    audio = candidates[0]
    return FileResponse(path=audio, media_type=AUDIO_MEDIA_TYPES[audio.suffix.lower()])


@router.get("/{job_id}/files/{kind}")
def get_file(request: Request, job_id: str, kind: FileKind) -> FileResponse:
    """Download one output of the job under its on-disk name."""
    _, directory = _job(request=request, job_id=job_id)
    name = FILE_NAMES[kind]
    path = _existing(directory=directory, name=name)
    media_type = "application/json" if name.endswith(".json") else "text/markdown"
    return FileResponse(path=path, media_type=media_type, filename=name)


@router.get("/{job_id}/transcript")
def get_transcript(
    request: Request,
    job_id: str,
    variant: Annotated[TranscriptVariant, Query()] = "original",
) -> dict[str, Any]:
    """Reader view: paragraphs of timed words plus the points to re-listen.

    The uncertainty threshold is the one chosen for this job, so the reader
    marks the same words as the Markdown written at the end of the job.
    """
    record, directory = _job(request=request, job_id=job_id)
    path = _existing(directory=directory, name=TRANSCRIPT_FILES[variant])
    transcript = load_transcript(path)
    settings: Settings = request.app.state.settings
    threshold = record.config.uncertain_threshold
    options = RenderOptions(
        uncertain_threshold=threshold,
        paragraph_gap_s=settings.paragraph_gap_s,
        paragraph_max_s=settings.paragraph_max_s,
    )
    paragraphs = build_paragraphs(transcript=transcript, options=options)
    points = build_review_points(transcript=transcript, threshold=threshold)
    return {
        "data": {
            "paragraphs": [[asdict(word) for word in words] for words in paragraphs],
            "review_points": [asdict(point) for point in points],
        },
        "meta": {},
    }

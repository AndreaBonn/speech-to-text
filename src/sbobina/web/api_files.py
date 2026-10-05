import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from starlette.responses import FileResponse

from sbobina.models import Transcript, load_transcript
from sbobina.render import RenderOptions
from sbobina.settings import Settings
from sbobina.web.errors import AudioNotIncludedError, NotFoundError
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
AUDIO_STEM = "audio"
FILE_NAMES: dict[str, str] = {
    "md": "audio.md",
    "json": "audio.json",
    "corrected_md": "audio.corretto.md",
    "corrected_json": "audio.corretto.json",
    "report": "audio.correzioni.md",
}
TranscriptVariant = Literal["original", "corrected"]
REVISION_CHARS = 16
TRANSCRIPT_FILES = {"original": "audio.json", "corrected": "audio.corretto.json"}


def find_job(request: Request, job_id: str) -> tuple[JobRecord, Path]:
    store: JobStore = request.app.state.job_store
    record = store.get(job_id=job_id)
    return record, store.jobs_dir / str(record.id)


def existing_file(directory: Path, name: str) -> Path:
    path = directory / name
    if not path.is_file():
        raise NotFoundError(entity="File", id=name)
    return path


@router.get("/{job_id}/audio")
def get_audio(request: Request, job_id: str) -> FileResponse:
    """Serve the uploaded recording; Starlette answers Range requests with 206."""
    record, directory = find_job(request=request, job_id=job_id)
    candidates = [
        path
        for path in directory.glob("audio.*")
        if path.suffix.lower() in AUDIO_MEDIA_TYPES
    ]
    if not candidates:
        if record.imported:
            raise AudioNotIncludedError()
        raise NotFoundError(entity="Audio", id=job_id)
    audio = candidates[0]
    return FileResponse(path=audio, media_type=AUDIO_MEDIA_TYPES[audio.suffix.lower()])


@router.get("/{job_id}/files/{kind}")
def get_file(request: Request, job_id: str, kind: FileKind) -> FileResponse:
    """Download one output of the job, named after the uploaded audio."""
    record, directory = find_job(request=request, job_id=job_id)
    name = FILE_NAMES[kind]
    path = existing_file(directory=directory, name=name)
    media_type = "application/json" if name.endswith(".json") else "text/markdown"
    return FileResponse(
        path=path,
        media_type=media_type,
        filename=download_name(source_name=record.source_name, name=name),
    )


def download_name(source_name: str, name: str) -> str:
    # "audio.corretto.md" + "Lezione 3.m4a" -> "Lezione 3.corretto.md", so
    # several lessons downloaded to one folder do not collide.
    if not source_name:
        return name
    return Path(source_name).stem + name.removeprefix(AUDIO_STEM)


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
    record, directory = find_job(request=request, job_id=job_id)
    path = existing_file(directory=directory, name=TRANSCRIPT_FILES[variant])
    return reader_payload(
        transcript=load_transcript(path),
        options=job_render_options(request=request, record=record),
        revision=transcript_revision(path.read_text(encoding="utf-8")),
    )


def transcript_revision(content: str) -> str:
    """Fingerprint of a saved transcript; an edit must quote the one it saw.

    Word indices shift after an edit that changes the word count, and a stale
    span can still match its expected text when words repeat ("la", "che").
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:REVISION_CHARS]


def job_render_options(request: Request, record: JobRecord) -> RenderOptions:
    """Paragraph limits of the app, uncertainty threshold chosen for the job."""
    settings: Settings = request.app.state.settings
    return RenderOptions(
        uncertain_threshold=record.config.uncertain_threshold,
        paragraph_gap_s=settings.paragraph_gap_s,
        paragraph_max_s=settings.paragraph_max_s,
    )


def reader_payload(
    transcript: Transcript, options: RenderOptions, revision: str
) -> dict[str, Any]:
    threshold = options.uncertain_threshold
    paragraphs = build_paragraphs(transcript=transcript, options=options)
    points = build_review_points(transcript=transcript, threshold=threshold)
    return {
        "data": {
            "paragraphs": [[asdict(word) for word in words] for words in paragraphs],
            "review_points": [asdict(point) for point in points],
        },
        "meta": {"revision": revision},
    }

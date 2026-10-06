"""Transcribe a lecture with AssemblyAI instead of faster-whisper (T053).

Same contract as `transcriber.transcribe_file`: audio path in, `Transcript`
out, progress on the same callback. The remote transcript and the uploaded
audio are deleted at the end whatever happened after the submit; a failed
deletion is a user-visible warning, never silent.
"""

import logging
from pathlib import Path

from sbobina.assemblyai_client import (
    AssemblyAIClient,
    ClientConfig,
    RemoteTranscriptionError,
)
from sbobina.assemblyai_mapping import TranscriptMeta, to_transcript
from sbobina.llm_errors import FailureKind, ProviderUnavailableError
from sbobina.models import Transcript
from sbobina.notices import USER_NOTICE
from sbobina.runtime_config import runtime_keys
from sbobina.settings import Settings
from sbobina.transcriber import ProgressCallback

logger = logging.getLogger(__name__)

# Progress is reported as a fraction: upload, then remote work, then reading.
_UPLOAD_SHARE = 0.3
_REMOTE_DONE = 0.9
_DONE = 1.0
# Remote work is usually a fraction of the audio length; long lectures stay
# well within two hours (the client never waits less than 15 minutes).
_MAX_REMOTE_WAIT_S = 7200.0
DELETE_FAILED_NOTICE = "Trascrizione remota non cancellata su AssemblyAI (id %s)"


def _report(on_progress: ProgressCallback | None, fraction: float) -> None:
    if on_progress is not None:
        on_progress(fraction, _DONE)


def _api_key(config: Settings) -> str:
    key = runtime_keys(settings=config).get("assemblyai")
    if not key:
        raise ProviderUnavailableError(
            kind=FailureKind.MISSING_KEY, provider="assemblyai", retry_after_s=None
        )
    return key


def _delete_quietly(client: AssemblyAIClient, transcript_id: str) -> None:
    try:
        client.delete(transcript_id=transcript_id)
    except (ProviderUnavailableError, RemoteTranscriptionError):
        logger.warning(DELETE_FAILED_NOTICE, transcript_id, extra={USER_NOTICE: True})


def _run_remote(
    client: AssemblyAIClient,
    audio_path: Path,
    config: Settings,
    on_progress: ProgressCallback | None,
) -> Transcript:
    upload_url = client.upload(
        audio_path=audio_path,
        on_progress=lambda sent, total: _report(
            on_progress=on_progress, fraction=_UPLOAD_SHARE * sent / max(total, 1)
        ),
    )
    transcript_id = client.submit(upload_url=upload_url, language=config.language)
    try:
        reply = client.wait(transcript_id=transcript_id, max_wait_s=_MAX_REMOTE_WAIT_S)
        _report(on_progress=on_progress, fraction=_REMOTE_DONE)
        meta = TranscriptMeta(
            source=str(audio_path),
            speech_model=str(reply.get("speech_model_used") or "universal"),
            language=config.language,
            duration=float(reply.get("audio_duration") or 0.0),
        )
        transcript = to_transcript(
            payload=client.sentences(transcript_id=transcript_id), meta=meta
        )
    finally:
        _delete_quietly(client=client, transcript_id=transcript_id)
    _report(on_progress=on_progress, fraction=_DONE)
    return transcript


def transcribe_file(
    audio_path: Path, config: Settings, on_progress: ProgressCallback | None = None
) -> Transcript:
    """Upload, transcribe remotely, convert; the remote copy is deleted."""
    client = AssemblyAIClient(
        config=ClientConfig(
            api_key=_api_key(config=config), request_timeout_s=config.cloud_timeout_s
        )
    )
    try:
        return _run_remote(
            client=client, audio_path=audio_path, config=config, on_progress=on_progress
        )
    finally:
        client.close()

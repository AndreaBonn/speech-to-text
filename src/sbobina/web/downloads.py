from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Literal

import httpx
import ollama
from faster_whisper.utils import _MODELS, available_models
from huggingface_hub import snapshot_download
from pydantic import BaseModel, Field, JsonValue, model_validator

from sbobina.settings import Settings
from sbobina.web.errors import ConflictError

logger = logging.getLogger(__name__)

DownloadSource = Literal["whisper", "ollama"]
DownloadStatus = Literal["running", "done", "failed"]
DownloadKey = tuple[str, str]
WHISPER_ALLOW_PATTERNS = [
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
]
POLL_INTERVAL_S = 0.5
# Finished downloads kept for the page; older ones are dropped.
MAX_FINISHED_STATES = 50
# Ollama model references: [namespace/]name[:tag], letters, digits, . _ - only.
OLLAMA_NAME = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9._-]+)*(:[A-Za-z0-9._-]+)?"
)
MAX_OLLAMA_NAME = 200


class DownloadRequest(BaseModel):
    source: DownloadSource
    name: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_name(self) -> DownloadRequest:
        if not self.name.strip():
            raise ValueError("Il nome del modello non può essere vuoto")
        if self.source == "whisper" and self.name not in available_models():
            raise ValueError("Modello Whisper non disponibile")
        is_valid_ollama = len(self.name) <= MAX_OLLAMA_NAME and OLLAMA_NAME.fullmatch(
            self.name
        )
        if self.source == "ollama" and not is_valid_ollama:
            raise ValueError("Nome del modello Ollama non valido (es. qwen3.5:9b)")
        return self


@dataclass(frozen=True)
class DownloadState:
    source: str
    name: str
    status: DownloadStatus
    completed: int = 0
    total: int | None = None
    message: str | None = None

    def to_json(self) -> dict[str, JsonValue]:
        fraction = self.completed / self.total if self.total else None
        return {
            "source": self.source,
            "name": self.name,
            "status": self.status,
            "completed": self.completed,
            "total": self.total,
            "fraction": fraction,
            "message": self.message,
        }


def _error_message(error: Exception) -> str:
    if isinstance(error, (ConnectionError, httpx.HTTPError)):
        return "Ollama non è raggiungibile."
    if isinstance(error, ollama.ResponseError):
        return f"Ollama ha rifiutato il download: {error}"
    return f"Download non riuscito: {error}"


def _set_completed(state: DownloadState, completed: int) -> DownloadState:
    return replace(state, completed=completed)


def _set_progress(
    state: DownloadState, completed: int, total: int | None
) -> DownloadState:
    return replace(state, completed=completed, total=total)


def _blob_bytes(blobs: Path | None) -> int:
    """Bytes in the repo's blobs folder, partial ``*.incomplete`` files included.

    huggingface_hub writes into ``blobs/<etag>.<uuid>.incomplete`` and creates
    the ``snapshots/`` pointer only when a file is complete, so the pointer
    paths stay empty for the whole download of ``model.bin``.
    """
    if blobs is None or not blobs.is_dir():
        return 0
    return sum(path.stat().st_size for path in blobs.iterdir() if path.is_file())


def _whisper_plan(repo_id: str) -> tuple[int | None, Path | None]:
    """Dry-run the snapshot: expected bytes to download and the blobs folder."""
    infos = snapshot_download(
        repo_id=repo_id, allow_patterns=WHISPER_ALLOW_PATTERNS, dry_run=True
    )
    assert isinstance(infos, list)
    pending = [info for info in infos if info.will_download]
    sizes = [size for size in (info.file_size for info in pending) if size is not None]
    total = sum(sizes) if pending and len(sizes) == len(pending) else None
    # local_path is <repo>/snapshots/<revision>/<file>.
    blobs = Path(pending[0].local_path).parents[2] / "blobs" if pending else None
    return total, blobs


class DownloadManager:
    """Runs one background thread per (source, name) model download."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._states: dict[DownloadKey, DownloadState] = {}
        self._threads: dict[DownloadKey, threading.Thread] = {}

    def start(self, source: str, name: str) -> DownloadState:
        key = (source, name)
        with self._lock:
            existing = self._states.get(key)
            if existing is not None and existing.status == "running":
                raise ConflictError(
                    message=f"Download di {name} già in corso",
                    code="DOWNLOAD_IN_PROGRESS",
                )
            state = DownloadState(source=source, name=name, status="running")
            self._states[key] = state
            self._evict_finished()
            # Daemon: Ctrl+C must stop the server even mid-download; the cache
            # does not reuse the partial file (huggingface_hub 1.33 starts a new
            # <etag>.<uuid>.incomplete on every attempt) and the user retries.
            thread = threading.Thread(
                target=self._run,
                args=(key,),
                name=f"download-{source}-{name}",
                daemon=True,
            )
            self._threads[key] = thread
        thread.start()
        return state

    def _evict_finished(self) -> None:
        finished = [
            key for key, state in self._states.items() if state.status != "running"
        ]
        for key in finished[: max(0, len(finished) - MAX_FINISHED_STATES + 1)]:
            del self._states[key]
            self._threads.pop(key, None)

    def list(self) -> list[DownloadState]:
        with self._lock:
            return list(self._states.values())

    def join(self, source: str, name: str, timeout: float | None = None) -> None:
        with self._lock:
            thread = self._threads.get((source, name))
        if thread is not None:
            thread.join(timeout=timeout)

    def _apply(
        self, key: DownloadKey, transform: Callable[[DownloadState], DownloadState]
    ) -> None:
        with self._lock:
            self._states[key] = transform(self._states[key])

    def _run(self, key: DownloadKey) -> None:
        source, name = key
        try:
            if source == "whisper":
                self._run_whisper(name=name, key=key)
            else:
                self._run_ollama(name=name, key=key)
            self._apply(key, lambda state: replace(state, status="done"))
        except Exception as error:
            logger.exception("Download %s/%s fallito", source, name)
            message = _error_message(error)
            self._apply(
                key, lambda state: replace(state, status="failed", message=message)
            )

    def _run_whisper(self, name: str, key: DownloadKey) -> None:
        repo_id = _MODELS[name]
        total, blobs = _whisper_plan(repo_id=repo_id)
        baseline = _blob_bytes(blobs=blobs)
        self._apply(key, lambda state: replace(state, total=total))
        stop = threading.Event()
        poller = threading.Thread(
            target=self._poll_whisper, args=(key, blobs, baseline, stop), daemon=True
        )
        poller.start()
        try:
            snapshot_download(repo_id=repo_id, allow_patterns=WHISPER_ALLOW_PATTERNS)
        finally:
            stop.set()
            poller.join()
        final = total if total is not None else _blob_bytes(blobs) - baseline
        self._apply(key, lambda state: replace(state, completed=final))

    def _poll_whisper(
        self, key: DownloadKey, blobs: Path | None, baseline: int, stop: threading.Event
    ) -> None:
        while not stop.wait(timeout=POLL_INTERVAL_S):
            try:
                # A partial file can be renamed between iterdir() and stat().
                completed = max(0, _blob_bytes(blobs=blobs) - baseline)
            except OSError:
                logger.warning("Avanzamento del download non leggibile", exc_info=True)
                continue
            self._apply(key, partial(_set_completed, completed=completed))

    def _run_ollama(self, name: str, key: DownloadKey) -> None:
        digests: dict[str, tuple[int, int | None]] = {}
        with ollama.Client(host=self._settings.ollama_host) as client:
            for progress in client.pull(model=name, stream=True):
                digest = progress.digest or progress.status or ""
                digests[digest] = (progress.completed or 0, progress.total)
                completed = sum(value for value, _ in digests.values())
                total = _summed_total(digests)
                self._apply(
                    key, partial(_set_progress, completed=completed, total=total)
                )


def _summed_total(digests: dict[str, tuple[int, int | None]]) -> int | None:
    raw = [total for _, total in digests.values()]
    known = [total for total in raw if total is not None]
    return sum(known) if raw and len(known) == len(raw) else None

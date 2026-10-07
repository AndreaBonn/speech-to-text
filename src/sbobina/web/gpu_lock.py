"""GPU arbitration between the web process's interactive LLM calls and the
supervisor's TRANSCRIBING stage (ADR D3).

Readers-writer lock, priority to the writer. The supervisor is the writer:
`transcription_lease` blocks until no interactive LLM call is in flight, then holds the
GPU exclusively for the whole TRANSCRIBING stage. Chat and practice grading are the
readers: `chat_turn` is non-blocking and raises `GpuBusyError` immediately
once a writer is waiting or active, so a steady stream of interactive requests
cannot starve the transcription forever. Readers may run concurrently with
each other: they use the same resident Ollama model, so shared calls do not
require another copy of the model in VRAM.

Chat and practice grading run in the web process, outside the supervisor's FIFO,
and need this arbiter. The queue's own children (pipeline/correct/study/generation)
are already serialized by the supervisor's FIFO.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Condition, Event

from sbobina.web.errors import ConflictError

STAGE_LABELS = {
    "transcribing": "una trascrizione",
    "embedding": "un'indicizzazione semantica",
}


class GpuBusyError(ConflictError):
    """Raised by `chat_turn` while the GPU is reserved by a writer."""

    def __init__(self, stage: str, estimate_s: float | None) -> None:
        super().__init__(
            message=f"GPU occupata da {STAGE_LABELS.get(stage, stage)} ({stage})",
            code="GPU_BUSY",
        )
        self.stage = stage
        self.estimate_s = estimate_s


class LeaseCancelledError(Exception):
    """Raised inside `transcription_lease` when `cancel_wait` interrupts it."""


class GpuArbiter:
    def __init__(self) -> None:
        self._condition = Condition()
        self._writer_waiting = False
        self._writer_active = False
        self._reader_count = 0
        self._cancelled = False
        self._stage: str | None = None
        self._estimate_s: float | None = None

    def status(self) -> tuple[str | None, float | None]:
        """Current stage/estimate while a writer is waiting or active, else
        `(None, None)`. Convenience for a chat status banner outside the
        409 path, where `GpuBusyError` already carries the same pair."""
        with self._condition:
            if self._writer_waiting or self._writer_active:
                return self._stage, self._estimate_s
            return None, None

    @contextmanager
    def chat_turn(self) -> Iterator[None]:
        """Non-blocking shared lease for an interactive LLM call. Raises `GpuBusyError`
        immediately if a transcription is active or waiting; never blocks."""
        with self._condition:
            if self._writer_waiting or self._writer_active:
                assert self._stage is not None
                raise GpuBusyError(stage=self._stage, estimate_s=self._estimate_s)
            self._reader_count += 1
        try:
            yield
        finally:
            with self._condition:
                self._reader_count -= 1
                self._condition.notify_all()

    @contextmanager
    def transcription_lease(
        self,
        stage: str,
        estimate_s: float | None = None,
        *,
        cancellation: Event | None = None,
    ) -> Iterator[None]:
        """Wait for readers and hold the GPU with priority over interactive calls.
        Raise `LeaseCancelledError` if `cancel_wait` interrupts the wait."""
        self._acquire_writer(
            stage=stage, estimate_s=estimate_s, cancellation=cancellation
        )
        try:
            yield
        finally:
            with self._condition:
                self._writer_active = False
                self._stage = None
                self._estimate_s = None
                self._condition.notify_all()

    def _acquire_writer(
        self,
        stage: str,
        estimate_s: float | None,
        cancellation: Event | None,
    ) -> None:
        with self._condition:
            if cancellation is not None and cancellation.is_set():
                raise LeaseCancelledError(stage)
            self._writer_waiting = True
            self._stage = stage
            self._estimate_s = estimate_s
            self._condition.wait_for(
                predicate=lambda: (
                    self._reader_count == 0
                    or self._cancelled
                    or (cancellation is not None and cancellation.is_set())
                )
            )
            if self._cancelled or (cancellation is not None and cancellation.is_set()):
                self._cancelled = False
                self._writer_waiting = False
                self._stage = None
                self._estimate_s = None
                self._condition.notify_all()
                raise LeaseCancelledError(stage)
            self._writer_waiting = False
            self._writer_active = True

    def cancel_wait(self) -> None:
        """Interrupt a pending `transcription_lease` wait, if any is in
        progress. A no-op otherwise, so it is safe to call unconditionally
        from the supervisor's stop/cancel without disturbing a future,
        unrelated lease attempt."""
        with self._condition:
            if self._writer_waiting:
                self._cancelled = True
                self._condition.notify_all()

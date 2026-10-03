"""GPU arbitration between the web process's chat (T042) and the
supervisor's TRANSCRIBING stage (ADR D3).

Readers-writer lock, priority to the writer. The supervisor is the writer:
`transcription_lease` blocks until no chat turn is in flight, then holds the
GPU exclusively for the whole TRANSCRIBING stage. Chat turns are the
readers: `chat_turn` is non-blocking and raises `GpuBusyError` immediately
once a writer is waiting or active, so a steady stream of chat requests
cannot starve the transcription forever. Readers may run concurrently with
each other: they all call Ollama with the same model and options, which
Ollama does not reload, so there is no VRAM conflict between them.

Only the chat (run in the web process, outside the supervisor's FIFO) needs
this arbiter. The queue's own children (pipeline/correct/study/generation)
are already serialized by the supervisor's FIFO.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Condition

from sbobina.web.errors import ConflictError


class GpuBusyError(ConflictError):
    """Raised by `chat_turn` while the GPU is reserved for transcription."""

    def __init__(self, stage: str, estimate_s: float | None) -> None:
        super().__init__(
            message=f"GPU occupata da una trascrizione ({stage})", code="GPU_BUSY"
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
        """Non-blocking shared lease for one chat turn. Raises `GpuBusyError`
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
        self, stage: str, estimate_s: float | None = None
    ) -> Iterator[None]:
        """Blocking exclusive lease for the TRANSCRIBING stage. Rejects new
        chat turns from the moment it starts waiting (priority to the
        writer), waits for in-flight chat turns to finish, then holds the
        GPU until the `with` block exits. Raises `LeaseCancelledError` if
        `cancel_wait` interrupts the wait (supervisor stop/cancel)."""
        with self._condition:
            self._writer_waiting = True
            self._stage = stage
            self._estimate_s = estimate_s
            self._condition.wait_for(
                predicate=lambda: self._reader_count == 0 or self._cancelled
            )
            if self._cancelled:
                self._cancelled = False
                self._writer_waiting = False
                self._stage = None
                self._estimate_s = None
                self._condition.notify_all()
                raise LeaseCancelledError(stage)
            self._writer_waiting = False
            self._writer_active = True
        try:
            yield
        finally:
            with self._condition:
                self._writer_active = False
                self._stage = None
                self._estimate_s = None
                self._condition.notify_all()

    def cancel_wait(self) -> None:
        """Interrupt a pending `transcription_lease` wait, if any is in
        progress. A no-op otherwise, so it is safe to call unconditionally
        from the supervisor's stop/cancel without disturbing a future,
        unrelated lease attempt."""
        with self._condition:
            if self._writer_waiting:
                self._cancelled = True
                self._condition.notify_all()

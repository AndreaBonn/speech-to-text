import threading
import time
from collections.abc import Callable

import pytest

from sbobina.web.gpu_lock import GpuArbiter, GpuBusyError, LeaseCancelledError


def wait_for(predicate: Callable[[], bool], timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail("Condition did not become true before timeout")
        time.sleep(0.01)


def _reader_count(arbiter: GpuArbiter) -> int:
    with arbiter._condition:
        return arbiter._reader_count


def _writer_waiting(arbiter: GpuArbiter) -> bool:
    with arbiter._condition:
        return arbiter._writer_waiting


def test_chat_turn_blocks_transcription_until_it_exits() -> None:
    arbiter = GpuArbiter()
    release_chat = threading.Event()
    lease_acquired = threading.Event()

    def chat() -> None:
        with arbiter.chat_turn():
            release_chat.wait(timeout=5)

    chat_thread = threading.Thread(target=chat)
    chat_thread.start()
    wait_for(predicate=lambda: _reader_count(arbiter) == 1)

    def writer() -> None:
        with arbiter.transcription_lease(stage="transcribing"):
            lease_acquired.set()

    writer_thread = threading.Thread(target=writer)
    writer_thread.start()
    wait_for(predicate=lambda: _writer_waiting(arbiter))
    assert not lease_acquired.is_set()

    release_chat.set()
    wait_for(predicate=lease_acquired.is_set)
    writer_thread.join(timeout=5)
    chat_thread.join(timeout=5)
    assert not writer_thread.is_alive()


def test_chat_rejected_for_entire_transcription_stage() -> None:
    arbiter = GpuArbiter()
    hold_stage = threading.Event()
    entered = threading.Event()

    def writer() -> None:
        with arbiter.transcription_lease(stage="transcribing"):
            entered.set()
            hold_stage.wait(timeout=5)

    writer_thread = threading.Thread(target=writer)
    writer_thread.start()
    wait_for(predicate=entered.is_set)

    with pytest.raises(GpuBusyError) as caught, arbiter.chat_turn():
        pass
    assert caught.value.stage == "transcribing"
    assert caught.value.code == "GPU_BUSY"

    hold_stage.set()
    writer_thread.join(timeout=5)
    assert not writer_thread.is_alive()


def test_writer_priority_rejects_new_chats_while_waiting() -> None:
    arbiter = GpuArbiter()
    release_first_chat = threading.Event()
    lease_acquired = threading.Event()

    def first_chat() -> None:
        with arbiter.chat_turn():
            release_first_chat.wait(timeout=5)

    first_thread = threading.Thread(target=first_chat)
    first_thread.start()
    wait_for(predicate=lambda: _reader_count(arbiter) == 1)

    def writer() -> None:
        with arbiter.transcription_lease(stage="transcribing"):
            lease_acquired.set()

    writer_thread = threading.Thread(target=writer)
    writer_thread.start()
    wait_for(predicate=lambda: _writer_waiting(arbiter))

    for _ in range(5):
        with pytest.raises(GpuBusyError), arbiter.chat_turn():
            pass

    assert not lease_acquired.is_set()
    release_first_chat.set()
    wait_for(predicate=lease_acquired.is_set)
    writer_thread.join(timeout=5)
    first_thread.join(timeout=5)


def test_cancel_wait_unblocks_pending_transcription_lease() -> None:
    arbiter = GpuArbiter()
    release_chat = threading.Event()
    cancelled = threading.Event()
    acquired = threading.Event()

    def chat() -> None:
        with arbiter.chat_turn():
            release_chat.wait(timeout=5)

    chat_thread = threading.Thread(target=chat)
    chat_thread.start()
    wait_for(predicate=lambda: _reader_count(arbiter) == 1)

    def writer() -> None:
        try:
            with arbiter.transcription_lease(stage="transcribing"):
                acquired.set()
        except LeaseCancelledError:
            cancelled.set()

    writer_thread = threading.Thread(target=writer)
    writer_thread.start()
    wait_for(predicate=lambda: _writer_waiting(arbiter))

    arbiter.cancel_wait()
    writer_thread.join(timeout=5)
    assert not writer_thread.is_alive()
    assert cancelled.is_set()
    assert not acquired.is_set()

    release_chat.set()
    chat_thread.join(timeout=5)

    # The arbiter is usable again: a stray cancel does not stick around.
    with arbiter.transcription_lease(stage="transcribing"):
        pass


def test_cancel_wait_without_a_pending_lease_is_a_noop() -> None:
    arbiter = GpuArbiter()
    arbiter.cancel_wait()
    with arbiter.transcription_lease(stage="transcribing"):
        pass


def test_chat_possible_again_after_stage_ends() -> None:
    arbiter = GpuArbiter()
    with arbiter.transcription_lease(stage="transcribing"):
        pass
    with arbiter.chat_turn():
        pass

"""Fallback chain over chat clients, ordered by provider/model priority.

A FallbackChain is itself a ChatClient (T014): it tries the configured
links in order, skips ones chain_policy currently marks ineligible, and
records which link actually served each request (ServedByRecorder).
InvalidResponseError is never absorbed here (Dis.2 of plan.md): the chain
only decides availability, so a JSON-shape failure propagates to the
caller instead of silently moving to the next link.
"""

import logging
import threading
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from sbobina.chain_policy import LinkState
from sbobina.chat_pipeline import ChatClient
from sbobina.correction import InvalidResponseError
from sbobina.llm_errors import ChainExhaustedError, ProviderUnavailableError
from sbobina.ollama_chat import ChatRequest

logger = logging.getLogger("sbobina")


@dataclass(frozen=True)
class ChainLink:
    """One provider/model pair tried by a `FallbackChain`."""

    provider: str
    model: str
    client: ChatClient


class ServedByRecorder:
    """Thread-safe count of how many replies each ``provider/model`` served."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: Counter[str] = Counter()

    def add(self, label: str) -> None:
        with self._lock:
            self._counts[label] += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)


def _label(link: ChainLink) -> str:
    return f"{link.provider}/{link.model}"


class FallbackChain:
    """A ``ChatClient`` that tries ``links`` in priority order.

    Parameters
    ----------
    links : Sequence[ChainLink]
        Providers to try, in priority order.
    now : Callable[[], float]
        Injected monotonic clock, so cooldowns are deterministic in tests.
    recorder : ServedByRecorder | None
        Shared counter of which link served each request. A fresh one is
        created when omitted.
    """

    def __init__(
        self,
        links: Sequence[ChainLink],
        *,
        now: Callable[[], float] = time.monotonic,
        recorder: ServedByRecorder | None = None,
    ) -> None:
        self._links = tuple(links)
        self._now = now
        self._lock = threading.Lock()
        self._states = [LinkState() for _ in self._links]
        self._last_failures: list[ProviderUnavailableError | None] = [
            None for _ in self._links
        ]
        self.recorder = recorder if recorder is not None else ServedByRecorder()

    @property
    def links(self) -> tuple[ChainLink, ...]:
        return self._links

    def __call__(self, request: ChatRequest) -> str:
        causes: list[ProviderUnavailableError] = []
        for index, link in enumerate(self._links):
            now = self._now()
            if not self._is_eligible(index=index, now=now):
                self._append_stale_cause(index=index, causes=causes)
                continue
            result = self._attempt(index=index, link=link, request=request, now=now)
            if result is None:
                self._append_stale_cause(index=index, causes=causes)
                continue
            return result
        raise ChainExhaustedError(causes=tuple(causes))

    def _is_eligible(self, index: int, now: float) -> bool:
        with self._lock:
            return self._states[index].eligible(now=now)

    def _append_stale_cause(
        self, index: int, causes: list[ProviderUnavailableError]
    ) -> None:
        cause = self._last_failures[index]
        if cause is not None:
            causes.append(cause)

    def _attempt(
        self, index: int, link: ChainLink, request: ChatRequest, now: float
    ) -> str | None:
        """Try one link. Returns the reply, or None after recording the failure."""
        try:
            result = link.client(replace(request, model=link.model))
        except InvalidResponseError:
            with self._lock:
                self._states[index] = self._states[index].record_invalid()
            raise
        except ProviderUnavailableError as err:
            self._record_failure(index=index, link=link, err=err, now=now)
            return None
        with self._lock:
            self._states[index] = self._states[index].record_success()
        self.recorder.add(_label(link))
        return result

    def _record_failure(
        self, index: int, link: ChainLink, err: ProviderUnavailableError, now: float
    ) -> None:
        with self._lock:
            self._states[index] = self._states[index].record_failure(
                kind=err.kind, retry_after_s=err.retry_after_s, now=now
            )
            self._last_failures[index] = err
        logger.info(
            "anello %d/%d non disponibile (%s), passo al successivo",
            index + 1,
            len(self._links),
            err.kind,
        )

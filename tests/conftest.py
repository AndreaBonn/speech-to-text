import sys
from collections.abc import Iterator

import httpx
import pytest

from sbobina.models import Segment, Transcript, Word


def make_word(text: str, start: float, probability: float = 0.99) -> Word:
    return Word(start=start, end=start + 0.4, text=text, probability=probability)


def make_segment(words: list[Word]) -> Segment:
    return Segment(start=words[0].start, end=words[-1].end, words=tuple(words))


def make_transcript(segments: list[Segment]) -> Transcript:
    return Transcript(
        source="lezione.m4a",
        model="large-v3",
        language="it",
        duration=segments[-1].end,
        segments=tuple(segments),
    )


@pytest.fixture(autouse=True)
def _keep_process_memory_limit() -> Iterator[None]:
    """Fail any test that lowers RLIMIT_AS of the pytest process itself.

    The limit cannot be raised again, so one such test leaves every later test
    unable to start threads or map memory: the suite hangs instead of failing.
    """
    if sys.platform == "win32":
        yield
        return
    import resource

    before = resource.getrlimit(resource.RLIMIT_AS)
    yield
    after = resource.getrlimit(resource.RLIMIT_AS)
    assert after == before, f"test changed RLIMIT_AS of pytest: {before} -> {after}"


# Real httpx connections an existing test legitimately makes (a local Ollama
# on this dev machine) or that Starlette's TestClient reports as its host.
_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "testserver"})

_real_handle_request = httpx.HTTPTransport.handle_request
_real_handle_async_request = httpx.AsyncHTTPTransport.handle_async_request


def _guarded_handle_request(
    self: httpx.HTTPTransport, request: httpx.Request
) -> httpx.Response:
    if request.url.host in _ALLOWED_HOSTS:
        return _real_handle_request(self, request)
    raise RuntimeError(
        f"blocked real network call in test: {request.method} {request.url}"
    )


async def _guarded_handle_async_request(
    self: httpx.AsyncHTTPTransport, request: httpx.Request
) -> httpx.Response:
    if request.url.host in _ALLOWED_HOSTS:
        return await _real_handle_async_request(self, request)
    raise RuntimeError(
        f"blocked real network call in test: {request.method} {request.url}"
    )


@pytest.fixture(autouse=True)
def _block_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any httpx call to a real host other than localhost/testserver.

    Provider adapters (T016-T018) and AssemblyAI talk to the network only
    through `httpx`. This patches the transport classes httpx builds by
    default (`HTTPTransport`/`AsyncHTTPTransport`) so an un-mocked call to
    a cloud provider fails loudly in the test that issued it, instead of
    silently reaching the internet. Unaffected: a `Client`/`AsyncClient`
    built with an explicit `transport=httpx.MockTransport(...)` never
    constructs these classes, and Starlette's `TestClient` (host
    "testserver") uses its own ASGI transport, so neither goes through
    this patch at all.
    """
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _guarded_handle_request)
    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", _guarded_handle_async_request
    )

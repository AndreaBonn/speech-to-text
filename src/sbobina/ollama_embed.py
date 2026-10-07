import logging
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx
from ollama import Client, EmbedResponse, ListResponse, ResponseError, ShowResponse

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 32
EMBEDDING_NUM_CTX = 2048
QUERY_KEEP_ALIVE = "30m"
MODEL_MISSING = "model_missing"
UNREACHABLE = "unreachable"
BAD_RESPONSE = "bad_response"
HTTP_NOT_FOUND = 404
HTTP_BAD_REQUEST = 400
CONTEXT_EXCEEDED = "exceeds the context length"
BOUNDARY_ERRORS = (ResponseError, ConnectionError, httpx.TransportError)


@dataclass(frozen=True)
class EmbeddingInput:
    text: str
    passage_id: str


@dataclass(frozen=True)
class EmbeddedText:
    vector: list[float]
    truncated: bool


@dataclass(frozen=True)
class ModelStatus:
    digest: str
    dimensions: int


class EmbeddingClient(Protocol):
    @property
    def embed(self) -> Callable[..., EmbedResponse]: ...


@dataclass(frozen=True)
class _EmbedRequest:
    model: str
    mode: Literal["query", "document"]


class EmbeddingUnavailableError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def embed_texts(
    client: EmbeddingClient,
    model: str,
    texts: Sequence[str | EmbeddingInput],
    mode: Literal["query", "document"],
) -> list[EmbeddedText]:
    """Embed preformatted texts; callers must validate_dimensions before use.

    Parameters
    ----------
    client, model, mode
        Injected client, model name and query/document execution mode.
    texts
        Strings (global zero-based index as passage_id) or inputs with IDs.
    """
    request = _EmbedRequest(model=model, mode=mode)
    inputs = [
        item
        if isinstance(item, EmbeddingInput)
        else EmbeddingInput(text=item, passage_id=str(index))
        for index, item in enumerate(texts)
    ]
    result: list[EmbeddedText] = []
    try:
        for start in range(0, len(inputs), EMBED_BATCH_SIZE):
            batch = inputs[start : start + EMBED_BATCH_SIZE]
            result.extend(_embed_batch(client=client, request=request, batch=batch))
    except BOUNDARY_ERRORS as error:
        raise _unavailable(error=error) from error
    return result


def _unavailable(error: Exception) -> EmbeddingUnavailableError:
    reason = BAD_RESPONSE
    if isinstance(error, (ConnectionError, httpx.TransportError)):
        reason = UNREACHABLE
    elif isinstance(error, ResponseError) and error.status_code == HTTP_NOT_FOUND:
        reason = MODEL_MISSING
    return EmbeddingUnavailableError(reason=reason)


def _is_context_exceeded(error: ResponseError) -> bool:
    return error.status_code == HTTP_BAD_REQUEST and CONTEXT_EXCEEDED in str(error)


def _request_vectors(
    client: EmbeddingClient,
    request: _EmbedRequest,
    texts: Sequence[str],
    truncate: bool,
) -> list[list[float]]:
    options = {"num_ctx": EMBEDDING_NUM_CTX}
    extra: dict[str, Any] = {}
    if request.mode == "query":
        options["num_gpu"] = 0
        extra["keep_alive"] = QUERY_KEEP_ALIVE
    inputs = list(texts)
    try:
        response = client.embed(
            model=request.model,
            input=inputs,
            options=options,
            truncate=truncate,
            **extra,
        )
    except ValueError as error:
        raise _unavailable(error=error) from error
    vectors = [list(vector) for vector in response.embeddings]
    if len(vectors) != len(texts) or any(
        not vector or not all(math.isfinite(value) for value in vector)
        for vector in vectors
    ):
        raise EmbeddingUnavailableError(reason=BAD_RESPONSE)
    return vectors


def _embed_batch(
    client: EmbeddingClient, request: _EmbedRequest, batch: Sequence[EmbeddingInput]
) -> list[EmbeddedText]:
    try:
        vectors = _request_vectors(
            client=client,
            request=request,
            texts=[item.text for item in batch],
            truncate=False,
        )
    except ResponseError as error:
        if not _is_context_exceeded(error=error):
            raise
        return [_embed_one(client=client, request=request, item=item) for item in batch]
    return [EmbeddedText(vector=vector, truncated=False) for vector in vectors]


def _embed_one(
    client: EmbeddingClient, request: _EmbedRequest, item: EmbeddingInput
) -> EmbeddedText:
    try:
        vectors = _request_vectors(
            client=client, request=request, texts=[item.text], truncate=False
        )
    except ResponseError as error:
        if not _is_context_exceeded(error=error):
            raise
        vectors = _request_vectors(
            client=client, request=request, texts=[item.text], truncate=True
        )
        logger.warning(
            "Embedding truncated: passage_id=%s characters=%s num_ctx=%s",
            item.passage_id,
            len(item.text),
            EMBEDDING_NUM_CTX,
        )
        return EmbeddedText(vector=vectors[0], truncated=True)
    return EmbeddedText(vector=vectors[0], truncated=False)


def model_status(*, host: str, model: str, timeout_s: float) -> ModelStatus:
    """Return the installed model digest from tags and dimensions from show.

    Parameters
    ----------
    host, model
        Ollama URL and exact model name in tags. This boundary never pulls.
    timeout_s
        Client timeout: callers hold a process-wide lock while this runs, so an
        Ollama that hangs must not block every chat turn.

    Returns
    -------
    ModelStatus
        Digest and positive dimensions, found by the family-independent suffix
        .embedding_length in modelinfo. Missing metadata raises bad_response.
    """
    try:
        client = Client(host=host, timeout=timeout_s)
        try:
            tags = client.list()
            info = client.show(model=model)
        except ValueError as error:
            raise _unavailable(error=error) from error
        return _read_model_status(tags=tags, info=info, model=model)
    except BOUNDARY_ERRORS as error:
        raise _unavailable(error=error) from error


def _read_model_status(
    tags: ListResponse, info: ShowResponse, model: str
) -> ModelStatus:
    entry = next((entry for entry in tags.models if entry.model == model), None)
    if entry is None:
        raise EmbeddingUnavailableError(reason=MODEL_MISSING)
    if not entry.digest:
        raise EmbeddingUnavailableError(reason=BAD_RESPONSE)
    return ModelStatus(digest=entry.digest, dimensions=_dimensions(info=info.modelinfo))


def _dimensions(info: Mapping[str, Any] | None) -> int:
    for key, value in (info or {}).items():
        if key.endswith(".embedding_length") and type(value) is int and value > 0:
            return value
    raise EmbeddingUnavailableError(reason=BAD_RESPONSE)


def validate_dimensions(
    embedded: Sequence[EmbeddedText], expected_dimensions: int
) -> None:
    """Reject vectors that differ from dimensions recorded in model_status."""
    if any(len(item.vector) != expected_dimensions for item in embedded):
        raise EmbeddingUnavailableError(reason=BAD_RESPONSE)

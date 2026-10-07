"""Fake Ollama client for the embedding boundary tests (tests/test_ollama_embed.py)."""

from typing import Any

from ollama import EmbedResponse, ListResponse, ResponseError, ShowResponse

MODEL = "qwen3-embedding:8b"
HOST = "http://ollama.invalid:11434"
OVER_CONTEXT = "exceeds the context length"


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.timeouts: list[float | None] = []
        self.probes: list[str] = []
        self.pull_calls = 0
        self.over_context: set[str] = set()
        self.broken_single: set[str] = set()
        self.failure: Exception | None = None
        self.fail_at = "embed"
        self.vectors: list[list[float]] | None = None
        self.tags = ListResponse(models=[ListResponse.Model(model=MODEL, digest="abc")])
        self.info = ShowResponse(model_info={"other_family.embedding_length": 4096})

    def embed(self, **kwargs: Any) -> EmbedResponse:
        self.calls.append(kwargs)
        if self.failure is not None and self.fail_at == "embed":
            raise self.failure
        texts = kwargs["input"]
        if len(texts) == 1 and texts[0] in self.broken_single:
            raise ResponseError(error="server error", status_code=500)
        if self.over_context.intersection(texts) and not kwargs["truncate"]:
            raise ResponseError(error=OVER_CONTEXT, status_code=400)
        vectors = self.vectors
        if vectors is None:
            vectors = [[float(len(text)), 1.0] for text in texts]
        return EmbedResponse(embeddings=vectors)

    def list(self) -> ListResponse:
        self.probes.append("list")
        if self.failure is not None and self.fail_at == "list":
            raise self.failure
        return self.tags

    def show(self, model: str) -> ShowResponse:
        self.probes.append(f"show:{model}")
        if self.failure is not None and self.fail_at == "show":
            raise self.failure
        return self.info

    def pull(self, **kwargs: Any) -> None:
        self.pull_calls += 1

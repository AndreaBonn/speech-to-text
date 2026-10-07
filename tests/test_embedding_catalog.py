import httpx
import pytest
from ollama import ListResponse, ShowResponse

from sbobina import ollama_embed


class CatalogClient:
    def __init__(self, **kwargs: object) -> None:
        self.calls: list[str] = []

    def list(self) -> ListResponse:
        return ListResponse(
            models=[ListResponse.Model(model=name) for name in ("chat", "embed")]
        )

    def show(self, *, model: str) -> ShowResponse:
        self.calls.append(model)
        return ShowResponse(
            model_info={},
            capabilities=["embedding"] if model == "embed" else ["completion"],
        )


def test_list_embedding_models_filters_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = CatalogClient()
    monkeypatch.setattr(ollama_embed, "Client", lambda **kw: client)
    assert ollama_embed.list_embedding_models(host="fake", timeout_s=2.0) == ["embed"]
    assert client.calls == ["chat", "embed"]


@pytest.mark.parametrize(
    "error,reason",
    [
        (httpx.ConnectError("down"), "unreachable"),
        (ValueError("invalid"), "bad_response"),
    ],
)
def test_list_embedding_models_maps_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception, reason: str
) -> None:
    def failed(**kwargs: object) -> CatalogClient:
        raise error

    monkeypatch.setattr(ollama_embed, "Client", failed)
    with pytest.raises(ollama_embed.EmbeddingUnavailableError) as caught:
        ollama_embed.list_embedding_models(host="fake", timeout_s=2.0)
    assert caught.value.reason == reason

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from ollama import ListResponse, ResponseError, ShowResponse
from ollama_embed_fixtures import HOST, MODEL, OVER_CONTEXT, FakeClient

from sbobina import ollama_embed as boundary
from sbobina.ollama_embed import (
    EmbeddedText,
    EmbeddingInput,
    EmbeddingUnavailableError,
    embed_texts,
    model_status,
    validate_dimensions,
)

TIMEOUT_S = 7.5


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeClient]:
    fake = FakeClient()

    def factory(*, host: str, timeout: float | None = None) -> FakeClient:
        assert host == HOST
        fake.timeouts.append(timeout)
        return fake

    monkeypatch.setattr(boundary, "Client", factory)
    yield fake
    assert fake.pull_calls == 0


@pytest.mark.parametrize("mode", ["document", "query"])
def test_embed_texts_batches_preserve_inputs_and_options(
    client: FakeClient, mode: Any
) -> None:
    texts = [f"passage-{index}" for index in range(70)]
    result = embed_texts(client=client, model=MODEL, texts=texts, mode=mode)
    assert [call["input"] for call in client.calls] == [
        texts[:32],
        texts[32:64],
        texts[64:],
    ]
    assert result == [
        EmbeddedText(vector=[float(len(text)), 1.0], truncated=False) for text in texts
    ]
    options = {"num_ctx": 2048}
    extra: dict[str, Any] = {}
    if mode == "query":
        options["num_gpu"] = 0
        extra["keep_alive"] = "30m"
    assert client.calls == [
        {"model": MODEL, "input": batch, "truncate": False, "options": options, **extra}
        for batch in [texts[:32], texts[32:64], texts[64:]]
    ]


@pytest.mark.parametrize("mode", ["document", "query"])
def test_embed_texts_truncates_only_over_context_passage(
    client: FakeClient, caplog: pytest.LogCaptureFixture, mode: Any
) -> None:
    client.over_context = {"long"}
    texts = [
        EmbeddingInput(text=text, passage_id=f"id-{text}")
        for text in ["ok", "long", "end"]
    ]
    result = embed_texts(client=client, model=MODEL, texts=texts, mode=mode)
    assert result == [
        EmbeddedText(vector=[2.0, 1.0], truncated=False),
        EmbeddedText(vector=[4.0, 1.0], truncated=True),
        EmbeddedText(vector=[3.0, 1.0], truncated=False),
    ]
    assert [(call["input"], call["truncate"]) for call in client.calls] == [
        (["ok", "long", "end"], False),
        (["ok"], False),
        (["long"], False),
        (["long"], True),
        (["end"], False),
    ]
    options = {"num_ctx": 2048, **({"num_gpu": 0} if mode == "query" else {})}
    assert all(call["options"] == options for call in client.calls)
    keep_alive = "30m" if mode == "query" else None
    assert [call.get("keep_alive") for call in client.calls] == [keep_alive] * 5
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert (record.levelname, record.name) == ("WARNING", "sbobina.ollama_embed")
    assert "passage_id=id-long" in record.message
    assert "characters=4" in record.message and "num_ctx=2048" in record.message


def test_embed_texts_fallback_id_is_global_index(
    client: FakeClient, caplog: pytest.LogCaptureFixture
) -> None:
    client.over_context = {"long"}
    result = embed_texts(
        client=client, model=MODEL, texts=["ok"] * 32 + ["long"], mode="document"
    )
    assert len(result) == 33 and result[-1].truncated
    assert "passage_id=32" in caplog.records[0].message


def test_embed_texts_empty_input_does_not_call_embed(client: FakeClient) -> None:
    assert embed_texts(client=client, model=MODEL, texts=[], mode="document") == []
    assert client.calls == []
    assert embed_texts(client=client, model=MODEL, texts=[""], mode="document") == [
        EmbeddedText(vector=[0.0, 1.0], truncated=False)
    ]
    assert len(client.calls) == 1


@pytest.mark.parametrize("stage", ["embed", "list", "show"])
@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (ResponseError(error="missing", status_code=404), "model_missing"),
        (ConnectionError("offline"), "unreachable"),
        (httpx.ConnectError("offline"), "unreachable"),
        (ResponseError(error="broken", status_code=500), "bad_response"),
        (ValueError("invalid response JSON"), "bad_response"),
    ],
)
def test_boundary_classifies_failures(
    client: FakeClient, stage: str, failure: Exception, reason: str
) -> None:
    client.failure, client.fail_at = failure, stage
    with pytest.raises(EmbeddingUnavailableError) as caught:
        if stage == "embed":
            embed_texts(client=client, model=MODEL, texts=["ok"], mode="document")
        else:
            model_status(host=HOST, model=MODEL, timeout_s=TIMEOUT_S)
    assert caught.value.reason == reason
    assert caught.value.__cause__ is failure
    assert client.calls if stage == "embed" else client.probes


@pytest.mark.parametrize(
    "failure",
    [
        ResponseError(error=OVER_CONTEXT, status_code=500),
        ResponseError(error="different bad request", status_code=400),
    ],
)
def test_embed_texts_does_not_retry_other_errors(
    client: FakeClient, failure: Exception
) -> None:
    client.failure = failure
    with pytest.raises(EmbeddingUnavailableError) as caught:
        embed_texts(client=client, model=MODEL, texts=["ok"], mode="document")
    assert caught.value.reason == "bad_response"
    assert len(client.calls) == 1
    assert client.calls[0]["truncate"] is False


@pytest.mark.parametrize(
    "vectors", [[], [[1.0], [2.0]], [[]], [[float("nan")]], [[float("inf")]]]
)
def test_embed_texts_rejects_bad_vectors(
    client: FakeClient, vectors: list[list[float]]
) -> None:
    client.vectors = vectors
    with pytest.raises(EmbeddingUnavailableError) as caught:
        embed_texts(client=client, model=MODEL, texts=["ok"], mode="document")
    assert caught.value.reason == "bad_response"
    assert len(client.calls) == 1


def test_model_status_selects_requested_digest_and_family_dimensions(
    client: FakeClient,
) -> None:
    client.tags = ListResponse(
        models=[ListResponse.Model(model="other", digest="wrong"), *client.tags.models]
    )
    status = model_status(host=HOST, model=MODEL, timeout_s=TIMEOUT_S)
    assert (status.digest, status.dimensions) == ("abc", 4096)
    assert status.model == MODEL
    assert set(client.probes) == {"list", f"show:{MODEL}"}


def test_model_status_absent_from_tags(client: FakeClient) -> None:
    client.tags = ListResponse(
        models=[ListResponse.Model(model="other", digest="wrong")]
    )
    with pytest.raises(EmbeddingUnavailableError) as caught:
        model_status(host=HOST, model=MODEL, timeout_s=TIMEOUT_S)
    assert caught.value.reason == "model_missing"
    assert "list" in client.probes


@pytest.mark.parametrize(
    "info",
    [
        None,
        {},
        {"other": 4096},
        {"x.embedding_length": 0},
        {"x.embedding_length": "4096"},
        {"x.embedding_length": True},
    ],
)
def test_model_status_invalid_dimensions_raise_bad_response(
    client: FakeClient, info: Any
) -> None:
    client.info = ShowResponse(model_info=info)

    with pytest.raises(EmbeddingUnavailableError) as caught:
        model_status(host=HOST, model=MODEL, timeout_s=TIMEOUT_S)

    assert caught.value.reason == "bad_response"
    assert f"show:{MODEL}" in client.probes


def test_model_status_show_value_error_raises_bad_response(client: FakeClient) -> None:
    failure = ValueError("invalid response JSON")
    client.failure, client.fail_at = failure, "show"

    with pytest.raises(EmbeddingUnavailableError) as caught:
        model_status(host=HOST, model=MODEL, timeout_s=TIMEOUT_S)

    assert caught.value.reason == "bad_response"
    assert caught.value.__cause__ is failure
    assert client.probes == ["list", f"show:{MODEL}"]


@pytest.mark.parametrize("digest", [None, ""])
def test_model_status_rejects_missing_digest(
    client: FakeClient, digest: str | None
) -> None:
    client.tags = ListResponse(models=[ListResponse.Model(model=MODEL, digest=digest)])
    with pytest.raises(EmbeddingUnavailableError) as caught:
        model_status(host=HOST, model=MODEL, timeout_s=TIMEOUT_S)
    assert caught.value.reason == "bad_response"
    assert "list" in client.probes


@pytest.mark.parametrize("size", [1024, 4096])
def test_validate_dimensions_matches_registered_model(
    client: FakeClient, size: int
) -> None:
    status = model_status(host=HOST, model=MODEL, timeout_s=TIMEOUT_S)
    client.vectors = [[1.0] * size]
    result = embed_texts(client=client, model=MODEL, texts=["ok"], mode="document")
    assert len(result[0].vector) == size
    if size == status.dimensions:
        validate_dimensions(embedded=result, expected_dimensions=status.dimensions)
    else:
        with pytest.raises(EmbeddingUnavailableError) as caught:
            validate_dimensions(embedded=result, expected_dimensions=status.dimensions)
        assert caught.value.reason == "bad_response"


def test_embed_texts_fallback_propagates_other_errors(client: FakeClient) -> None:
    client.over_context = {"long"}
    client.broken_single = {"broken"}
    texts = [
        EmbeddingInput(text=text, passage_id=f"id-{text}")
        for text in ["long", "broken", "ok"]
    ]

    with pytest.raises(EmbeddingUnavailableError) as caught:
        embed_texts(client=client, model=MODEL, texts=texts, mode="document")

    assert caught.value.reason == "bad_response"
    assert all(
        call["truncate"] is False
        for call in client.calls
        if call["input"] == ["broken"]
    )


def test_model_status_passes_the_timeout_to_the_client(client: FakeClient) -> None:
    model_status(host=HOST, model=MODEL, timeout_s=TIMEOUT_S)

    assert client.timeouts == [TIMEOUT_S]

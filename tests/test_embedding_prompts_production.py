import pytest

from sbobina.embedding_prompts import (
    EMBEDDING_PROMPT_VERSION,
    embedding_threshold,
    format_document_for_production,
    format_query,
)


def test_format_query_qwen_matches_evaluated_instruction_exactly() -> None:
    assert format_query(model="qwen3-embedding:8b", text="Che cos’è il possesso?") == (
        "Instruct: Given a question, retrieve relevant passages that answer it\n"
        "Query:Che cos’è il possesso?"
    )


def test_format_query_gemma_uses_search_instruction() -> None:
    assert format_query(model="embeddinggemma:latest", text="il possesso") == (
        "task: search result | query: il possesso"
    )


@pytest.mark.parametrize("model", ["nomic-embed-text", "bge-m3"])
def test_format_query_unprefixed_models_preserve_text(model: str) -> None:
    assert format_query(model=model, text="il possesso") == "il possesso"


def test_embedding_threshold_evaluated_model_returns_measured_floor() -> None:
    assert embedding_threshold(model="qwen3-embedding:8b") == 0.46


def test_embedding_threshold_unmeasured_model_has_no_floor() -> None:
    assert embedding_threshold(model="nomic-embed-text") is None
    assert embedding_threshold(model="qwen3-embedding:8b") == 0.46


def test_embedding_prompt_version_is_an_integer() -> None:
    assert isinstance(EMBEDDING_PROMPT_VERSION, int)


@pytest.mark.parametrize("model", ["qwen3-embedding:8b", "bge-m3", "nomic-embed-text"])
@pytest.mark.parametrize("text", ["Il possesso è un diritto.\n", ""])
def test_format_document_for_production_without_document_prompt_preserves_text(
    model: str, text: str
) -> None:
    assert format_document_for_production(model=model, text=text) == text


def test_format_document_for_production_gemma_uses_measured_document_prompt() -> None:
    assert format_document_for_production(
        model="embeddinggemma:latest", text="Il possesso è un diritto."
    ) == "title: none | text: Il possesso è un diritto."

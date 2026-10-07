import pytest

from sbobina import embedding_prompts
from sbobina.embedding_prompts import apply_query_instruction, format_document
from sbobina.hybrid_eval import cache_file_name


class TestApplyQueryInstruction:
    def test_disabled_returns_question_unchanged(self) -> None:
        assert apply_query_instruction(
            question="il possesso", enabled=False, model="qwen3-embedding:0.6b"
        ) == ("il possesso")

    def test_enabled_wraps_qwen3_with_instruction_prefix(self) -> None:
        result = apply_query_instruction(
            question="il possesso", enabled=True, model="qwen3-embedding:8b"
        )

        assert result.startswith("Instruct:")
        assert result.endswith("Query:il possesso")

    def test_enabled_wraps_embeddinggemma_with_search_task_prefix(self) -> None:
        result = apply_query_instruction(
            question="il possesso", enabled=True, model="embeddinggemma:latest"
        )

        assert result == "task: search result | query: il possesso"

    def test_enabled_leaves_bge_m3_query_unchanged(self) -> None:
        assert apply_query_instruction(
            question="il possesso", enabled=True, model="bge-m3"
        ) == ("il possesso")


class TestFormatDocument:
    def test_embeddinggemma_document_gets_title_none_prefix(self) -> None:
        assert format_document(text="Il possesso è...", model="embeddinggemma") == (
            "title: none | text: Il possesso è..."
        )

    def test_qwen3_document_is_left_unchanged(self) -> None:
        assert format_document(text="Il possesso è...", model="qwen3-embedding:4b") == (
            "Il possesso è..."
        )

    def test_bge_m3_document_is_left_unchanged(self) -> None:
        assert format_document(text="Il possesso è...", model="bge-m3") == (
            "Il possesso è..."
        )


class TestCacheFileName:
    def test_names_the_model_and_its_document_prompt(self) -> None:
        name = cache_file_name(model="qwen3-embedding:8b")

        assert name.startswith("qwen3-embedding_8b-")
        assert name.endswith(".npz")

    def test_same_model_gives_a_stable_name(self) -> None:
        assert cache_file_name(model="bge-m3") == cache_file_name(model="bge-m3")

    def test_models_with_different_document_prompts_get_different_names(self) -> None:
        qwen = cache_file_name(model="qwen3-embedding:8b").split("-")[-1]
        gemma = cache_file_name(model="embeddinggemma").split("-")[-1]

        assert qwen != gemma

    def test_changed_document_template_changes_the_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        before = cache_file_name(model="embeddinggemma")
        monkeypatch.setattr(
            embedding_prompts, "GEMMA_DOCUMENT_TEMPLATE", "title: x | text: {text}"
        )

        assert cache_file_name(model="embeddinggemma") != before


class TestUnknownModelFamily:
    def test_query_prompt_for_unknown_family_raises(self) -> None:
        with pytest.raises(ValueError, match="nomic-embed-text"):
            apply_query_instruction(
                question="il possesso", enabled=True, model="nomic-embed-text"
            )

    def test_document_prompt_for_unknown_family_raises(self) -> None:
        with pytest.raises(ValueError, match="nomic-embed-text"):
            format_document(text="Il possesso è...", model="nomic-embed-text")

    def test_disabled_instruction_does_not_need_a_known_family(self) -> None:
        assert apply_query_instruction(
            question="il possesso", enabled=False, model="nomic-embed-text"
        ) == ("il possesso")

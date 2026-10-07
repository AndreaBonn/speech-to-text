import pydantic
import pytest
from pydantic import SecretStr

from sbobina.settings import LlmChainEntry, Settings
from sbobina.web.job_models import JobConfig

SENTINEL = "sk-SENTINEL-do-not-leak"


def test_settings_semantic_search_defaults_to_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(name="SBOBINA_SEMANTIC_SEARCH", raising=False)

    assert Settings().semantic_search is True


def test_settings_semantic_search_can_be_disabled_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(name="SBOBINA_SEMANTIC_SEARCH", value="false")

    assert Settings().semantic_search is False


def test_settings_embedding_model_defaults_to_evaluated_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(name="SBOBINA_EMBEDDING_MODEL", raising=False)

    assert Settings().embedding_model == "qwen3-embedding:8b"


def test_settings_embedding_model_accepts_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(name="SBOBINA_EMBEDDING_MODEL", value="x")

    assert Settings().embedding_model == "x"


def test_settings_course_doc_max_mb_accepts_the_package_member_cap() -> None:
    assert Settings(course_doc_max_mb=200).course_doc_max_mb == 200


def test_settings_course_doc_max_mb_above_package_member_cap_raises() -> None:
    # C5: a document larger than a package member could never be re-imported.
    with pytest.raises(pydantic.ValidationError):
        Settings(course_doc_max_mb=201)


def test_settings_llm_engine_defaults_to_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(name="SBOBINA_LLM_ENGINE", raising=False)

    assert Settings().llm_engine == "local"


def test_settings_llm_chain_parses_from_env_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        name="SBOBINA_LLM_CHAIN", value='[{"provider":"groq","model":"llama-3.3"}]'
    )

    assert Settings().llm_chain == [LlmChainEntry(provider="groq", model="llama-3.3")]


def test_settings_llm_chain_unknown_provider_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        name="SBOBINA_LLM_CHAIN", value='[{"provider":"mistral","model":"x"}]'
    )

    with pytest.raises(pydantic.ValidationError):
        Settings()


def test_settings_llm_chain_rejects_duplicate_provider_model_pairs() -> None:
    entry = LlmChainEntry(provider="groq", model="llama")
    with pytest.raises(pydantic.ValidationError, match="duplicate"):
        Settings(llm_chain=[entry, entry])


def test_settings_llm_chain_rejects_more_than_eight_links() -> None:
    entries = [LlmChainEntry(provider="groq", model=f"m{i}") for i in range(9)]
    with pytest.raises(pydantic.ValidationError, match="massimo"):
        Settings(llm_chain=entries)


def test_settings_llm_chain_entry_rejects_an_empty_model() -> None:
    with pytest.raises(pydantic.ValidationError):
        LlmChainEntry(provider="groq", model="   ")


def test_settings_repr_does_not_expose_a_configured_api_key_in_clear() -> None:
    config = Settings(groq_api_key=SecretStr(SENTINEL))

    assert SENTINEL not in repr(config)


def test_settings_model_dump_json_does_not_expose_a_configured_api_key() -> None:
    config = Settings(groq_api_key=SecretStr(SENTINEL))

    assert SENTINEL not in config.model_dump_json()


def test_settings_survives_the_job_config_merge_round_trip_without_losing_fields() -> (
    None
):
    """Mirrors stage_runner._prepare_stage: settings merged with a JobConfig dump.

    `llm_chain` and the API keys are not JobConfig fields, so they must pass
    through the merge unchanged from `settings.model_dump()`.
    """
    config = Settings(
        groq_api_key=SecretStr(SENTINEL),
        llm_engine="api",
        llm_chain=[LlmChainEntry(provider="groq", model="llama-3.3")],
    )
    job_config = JobConfig.from_settings(config=config)

    merged = Settings.model_validate({**config.model_dump(), **job_config.model_dump()})

    assert merged.groq_api_key is not None
    assert merged.groq_api_key.get_secret_value() == SENTINEL
    assert merged.llm_engine == "api"
    assert merged.llm_chain == [LlmChainEntry(provider="groq", model="llama-3.3")]

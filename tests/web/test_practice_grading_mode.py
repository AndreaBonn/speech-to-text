import pytest
from pydantic import SecretStr

from sbobina import platform_info
from sbobina.settings import LlmChainEntry, Settings
from sbobina.web.practice_grading import grading_mode


@pytest.fixture
def cpu_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def resolve_cpu(
        info: platform_info.PlatformInfo, requested: platform_info.RuntimeRequest
    ) -> platform_info.RuntimeChoice:
        return platform_info.RuntimeChoice(
            device="cpu",
            compute_type="int8",
            whisper_model="large-v3-turbo",
            cpu_threads=4,
            reason="test",
        )

    monkeypatch.setattr(platform_info, "resolve_runtime", resolve_cpu)


def _api_settings(groq_key: str | None) -> Settings:
    return Settings(
        llm_engine="api",
        llm_chain=[LlmChainEntry(provider="groq", model="llama-x")],
        groq_api_key=SecretStr(groq_key) if groq_key is not None else None,
    )


def test_grading_mode_auto_api_with_key_on_cpu_uses_judge(cpu_only: None) -> None:
    assert grading_mode(settings=_api_settings(groq_key="gsk-test-key")) == "judge"


def test_grading_mode_auto_api_without_key_on_cpu_falls_back_to_self(
    cpu_only: None,
) -> None:
    assert grading_mode(settings=_api_settings(groq_key=None)) == "self"


def test_grading_mode_auto_local_on_cpu_uses_self(cpu_only: None) -> None:
    assert grading_mode(settings=Settings(llm_engine="local")) == "self"


def test_grading_mode_explicit_self_wins_over_cloud_key(cpu_only: None) -> None:
    settings = _api_settings(groq_key="gsk-test-key").model_copy(
        update={"practice_grading_mode": "self"}
    )
    assert grading_mode(settings=settings) == "self"

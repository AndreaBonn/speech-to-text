import pytest

from sbobina.web.processes import _child_env

SENTINEL_KEY = "sk-SENTINEL-0123456789abcdef"


def test_child_env_untrusted_drops_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SBOBINA_GROQ_API_KEY", SENTINEL_KEY)
    monkeypatch.setenv("SBOBINA_ASSEMBLYAI_API_KEY", SENTINEL_KEY)
    monkeypatch.setenv("SBOBINA_OLLAMA_HOST", "http://localhost:11434")

    env = _child_env(untrusted=True)

    assert SENTINEL_KEY not in env.values()
    assert env["SBOBINA_OLLAMA_HOST"] == "http://localhost:11434"


def test_child_env_trusted_keeps_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SBOBINA_GROQ_API_KEY", SENTINEL_KEY)

    assert _child_env()["SBOBINA_GROQ_API_KEY"] == SENTINEL_KEY

"""T026: a full api-engine correction never writes a key outside its header."""

import json
import logging
from pathlib import Path

import httpx
import pytest
from conftest import make_segment, make_transcript, make_word

from sbobina.models import save_transcript
from sbobina.pipeline import correct_to_dir
from sbobina.settings import LlmChainEntry, Settings

GROQ_KEY = "gsk-SENTINEL-0123456789abcdef"
OPENAI_KEY = "sk-SENTINEL-fedcba9876543210"
EMPTY_CORRECTION = json.dumps({"correzioni": []})


def _fake_provider(seen: list[httpx.Request]) -> object:
    def handle_request(
        self: httpx.HTTPTransport, request: httpx.Request
    ) -> httpx.Response:
        seen.append(request)
        if request.url.host == "api.groq.com":
            return httpx.Response(
                401, json={"error": {"message": f"bad key {GROQ_KEY}"}}
            )
        reply = {
            "choices": [
                {"message": {"content": EMPTY_CORRECTION}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        return httpx.Response(200, json=reply)

    return handle_request


def test_api_correction_keeps_keys_out_of_files_and_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    seen: list[httpx.Request] = []
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _fake_provider(seen))
    monkeypatch.setenv("SBOBINA_GROQ_API_KEY", GROQ_KEY)
    monkeypatch.setenv("SBOBINA_OPENAI_API_KEY", OPENAI_KEY)
    transcript = make_transcript(
        [make_segment([make_word("Buongiorno", 0.0), make_word(" a tutti", 0.5)])]
    )
    json_path = tmp_path / "lezione.json"
    save_transcript(transcript, json_path)
    config = Settings(
        llm_engine="api",
        llm_chain=[
            LlmChainEntry(provider="groq", model="llama-x"),
            LlmChainEntry(provider="openai", model="gpt-x"),
        ],
        llm_ollama_fallback=False,
    )

    with caplog.at_level(logging.DEBUG):
        outcome = correct_to_dir(json_path, config=config, subject=None)

    written = "".join(p.read_text(encoding="utf-8") for p in tmp_path.iterdir())
    assert outcome.corrected_json is not None
    assert "openai/gpt-x" in written
    for key in (GROQ_KEY, OPENAI_KEY):
        assert key not in written
        assert key not in caplog.text
    headers = {r.url.host: r.headers.get("authorization") for r in seen}
    assert headers["api.groq.com"] == f"Bearer {GROQ_KEY}"
    assert headers["api.openai.com"] == f"Bearer {OPENAI_KEY}"

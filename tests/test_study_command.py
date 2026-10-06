import pytest

from sbobina import llm_corrector, ollama_chat, study_command
from sbobina.llm_chain import FallbackChain, ServedByRecorder
from sbobina.ollama_chat import ChatRequest
from sbobina.settings import LlmChainEntry, Settings


def test_prepare_chat_ensures_the_model_then_sends_through_one_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    ensured: list[tuple[str, str]] = []
    clients: list[object] = []
    sent: list[tuple[object, ChatRequest]] = []

    class RecordingClient:
        def __init__(self, host: str) -> None:
            order.append("client")
            self.host = host
            clients.append(self)

    def ensure_model(model: str, host: str) -> None:
        order.append("ensure")
        ensured.append((model, host))

    def chat_json(client: object, request: ChatRequest) -> str:
        order.append("chat")
        sent.append((client, request))
        return '{"ok": true}'

    monkeypatch.setattr(llm_corrector, "ensure_model", ensure_model)
    monkeypatch.setattr("ollama.Client", RecordingClient)
    monkeypatch.setattr(ollama_chat, "chat_json", chat_json)

    chat = study_command._prepare_chat(model="qwen", host="http://ollama:11434")
    request = ChatRequest(model="qwen", system_prompt="s", user_message="u", schema={})

    assert chat(request) == '{"ok": true}'
    assert order.index("ensure") < order.index("chat")
    assert ensured == [("qwen", "http://ollama:11434")]
    assert sent == [(clients[0], request)]


def test_prepare_chat_api_engine_builds_chain_recording_served_by() -> None:
    config = Settings(
        llm_engine="api",
        llm_chain=[LlmChainEntry(provider="groq", model="llama-x")],
        llm_ollama_fallback=False,
    )
    recorder = ServedByRecorder()

    chat = study_command._prepare_chat(
        model="qwen", host="http://ollama:11434", config=config, recorder=recorder
    )

    assert isinstance(chat, FallbackChain)
    assert [(link.provider, link.model) for link in chat.links] == [("groq", "llama-x")]
    assert chat.recorder is recorder

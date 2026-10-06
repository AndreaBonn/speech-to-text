"""Single construction point for every ChatClient in the app (T022).

``build_chat_client`` is the only place that turns ``Settings`` plus
configured keys into a usable client: the ``local`` engine keeps today's
Ollama-only path verbatim (``ensure_model`` included, same lazy
``from ollama import Client`` import so existing tests that monkeypatch
``ollama.Client`` still work); the ``api`` engine builds a ``FallbackChain``
over the configured providers plus Ollama as the optional last link, with
no network call during construction.

Callers own the ``recorder`` (``ServedByRecorder``): passing one in is how
they get ``served_by`` back, via ``recorder.snapshot()`` after the call(s)
complete, or via the returned ``FallbackChain.recorder`` when none was
given for the ``api`` engine. For the ``local`` engine a recorder, when
given, is fed one label per successful call (``"ollama/<model>"``) so every
caller can read ``served_by`` the same way regardless of engine; this is
pure bookkeeping for uniformity, not a chain decision.

``keys_from_settings`` reads only the env-sourced ``SecretStr`` fields of
``Settings``: F2 adds a second source (the credentials file in the config
dir), so this factory depends on a plain ``Mapping[str, str]`` handed in by
the caller rather than on ``Settings`` directly, keeping that addition a
caller concern instead of a factory rewrite.
"""

from collections.abc import Mapping

from sbobina import llm_corrector, ollama_chat
from sbobina.chat_pipeline import ChatClient
from sbobina.llm_chain import ChainLink, FallbackChain, ServedByRecorder
from sbobina.llm_errors import FailureKind, ProviderUnavailableError
from sbobina.ollama_chat import ChatRequest
from sbobina.providers.anthropic import make_anthropic_client
from sbobina.providers.ollama_link import Guard, make_ollama_link_client
from sbobina.providers.openai_compat import PROFILES, make_openai_compat_client
from sbobina.settings import LlmChainEntry, LlmProvider, Settings

_KEY_FIELDS: dict[LlmProvider, str] = {
    "groq": "groq_api_key",
    "gemini": "gemini_api_key",
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
}


def keys_from_settings(settings: Settings) -> dict[str, str]:
    """Provider -> plaintext key, only for providers that have one configured."""
    keys: dict[str, str] = {}
    for provider, field_name in _KEY_FIELDS.items():
        secret = getattr(settings, field_name)
        if secret is not None:
            keys[provider] = secret.get_secret_value()
    return keys


def ensure_ready(settings: Settings) -> None:
    """Warm up the ``local`` engine's model; a no-op for ``api`` (never pulls)."""
    if settings.llm_engine == "local":
        llm_corrector.ensure_model(
            model=settings.ollama_model, host=settings.ollama_host
        )


def effective_model_label(settings: Settings) -> str:
    """Model label for persisted records: the plain model locally, a chain
    summary on ``api`` (plan.md T023: results no longer carry a single real
    model name once a fallback chain can serve them)."""
    if settings.llm_engine == "local":
        return settings.ollama_model
    names = [f"{entry.provider}/{entry.model}" for entry in settings.llm_chain]
    if settings.llm_ollama_fallback:
        names.append(f"ollama/{settings.ollama_model}")
    return "api: " + " > ".join(names)


def build_chat_client(
    settings: Settings,
    keys: Mapping[str, str],
    guard: Guard | None = None,
    recorder: ServedByRecorder | None = None,
) -> ChatClient:
    """Build the ``ChatClient`` for ``settings.llm_engine``.

    Parameters
    ----------
    settings : Settings
        Engine, chain and timeouts to build from.
    keys : Mapping[str, str]
        Provider -> plaintext key, from ``keys_from_settings`` (plus any
        later source a caller merges in).
    guard : Guard | None
        Context manager factory applied only to the Ollama link (GPU
        arbitration); ignored on the ``local`` engine, which runs
        unguarded like today.
    recorder : ServedByRecorder | None
        Shared ``served_by`` counter; see the module docstring.
    """
    if settings.llm_engine == "local":
        return _build_local_client(settings=settings, recorder=recorder)
    return _build_api_client(
        settings=settings, keys=keys, guard=guard, recorder=recorder
    )


def has_cloud_key(settings: Settings) -> bool:
    """True when the api engine has a key for at least one chain link."""
    if settings.llm_engine != "api":
        return False
    keys = keys_from_settings(settings=settings)
    return any(entry.provider in keys for entry in settings.llm_chain)


def build_from_settings(
    settings: Settings,
    recorder: ServedByRecorder | None = None,
    guard: Guard | None = None,
) -> ChatClient:
    """Build the client with the keys every caller resolves the same way."""
    return build_chat_client(
        settings=settings,
        keys=keys_from_settings(settings=settings),
        guard=guard,
        recorder=recorder,
    )


def _build_local_client(
    settings: Settings, recorder: ServedByRecorder | None
) -> ChatClient:
    from ollama import Client

    ensure_ready(settings=settings)
    client = Client(host=settings.ollama_host)

    def _call(request: ChatRequest) -> str:
        reply = ollama_chat.chat_json(client=client, request=request)
        if recorder is not None:
            recorder.add(f"ollama/{request.model}")
        return reply

    return _call


def _missing_key_client(label: str) -> ChatClient:
    def _call(request: ChatRequest) -> str:
        raise ProviderUnavailableError(
            kind=FailureKind.MISSING_KEY, provider=label, retry_after_s=None
        )

    return _call


def _cloud_adapter(provider: LlmProvider, api_key: str, timeout_s: float) -> ChatClient:
    if provider == "anthropic":
        return make_anthropic_client(api_key=api_key, timeout_s=timeout_s)
    return make_openai_compat_client(
        profile=PROFILES[provider], api_key=api_key, timeout_s=timeout_s
    )


def _chain_link(
    entry: LlmChainEntry, keys: Mapping[str, str], settings: Settings
) -> ChainLink:
    label = f"{entry.provider}/{entry.model}"
    key = keys.get(entry.provider)
    client = (
        _missing_key_client(label=label)
        if key is None
        else _cloud_adapter(
            provider=entry.provider, api_key=key, timeout_s=settings.cloud_timeout_s
        )
    )
    return ChainLink(provider=entry.provider, model=entry.model, client=client)


def _ollama_fallback_link(settings: Settings, guard: Guard | None) -> ChainLink:
    client = make_ollama_link_client(
        model_host=settings.ollama_host, timeout_s=None, guard=guard
    )
    return ChainLink(provider="ollama", model=settings.ollama_model, client=client)


def _build_api_client(
    settings: Settings,
    keys: Mapping[str, str],
    guard: Guard | None,
    recorder: ServedByRecorder | None,
) -> ChatClient:
    links = [
        _chain_link(entry=entry, keys=keys, settings=settings)
        for entry in settings.llm_chain
    ]
    if settings.llm_ollama_fallback:
        links.append(_ollama_fallback_link(settings=settings, guard=guard))
    return FallbackChain(links=links, recorder=recorder)

"""Logging filter that redacts API keys and other secrets from log output.

A `logging.Filter`, not a `Formatter`: redaction must run before any
formatter turns the record into text, and a filter mutates the record in
place so every handler downstream sees the redacted version. It is attached
to HANDLERS, not to loggers: a filter on a logger does not run on records a
child logger (e.g. ``sbobina.cli``) propagates straight past it to an
ancestor's handlers, and uvicorn's own loggers attach their own handlers
with ``propagate=False`` (S3, review di sicurezza del piano 003).
"""

import logging
import re
import threading
from collections.abc import Callable, Iterable
from pathlib import Path

from sbobina.config_dir import ConfigDirUnsafeError, resolve_config_dir
from sbobina.credential_store import CredentialStore, resolve_keys
from sbobina.settings import Settings

logger = logging.getLogger(__name__)

_REDACTED = "***"
_UNSET: object = object()

# Handlers to patch: root (reaches every "sbobina.*" logger via propagation)
# plus the loggers uvicorn configures with their own handlers and
# propagate=False, which root's filter would otherwise never see.
_TARGET_LOGGER_NAMES = ("", "uvicorn", "uvicorn.error", "uvicorn.access", "httpx")

# Key-shaped substrings redacted even when the value is not one of the
# known settings (e.g. a key pasted into an error message by a provider SDK).
# Length-bounded so short, unrelated words are left alone.
_KEY_PATTERNS = (
    re.compile(r"sk-proj-[A-Za-z0-9_-]{16,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"gsk_[A-Za-z0-9_-]{16,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{16,}"),
)


class _CachedKeyStoreSource:
    """Re-reads `credentials.json` only when its mtime changes.

    `SecretRedactionFilter.filter` runs on every log record, so re-opening
    and re-parsing the file on each call (as `CredentialStore.get_keys` does)
    would cost a stat *and* a read per log line. A stat alone is cheap and
    the cache only needs invalidating when the file actually changed, which
    is exactly what the mtime says (D4: a key added via the UI after
    `install_redaction` ran must still be redacted on the next log line).
    """

    def __init__(self, settings: Settings, store: CredentialStore) -> None:
        self._settings = settings
        self._store = store
        self._cached_mtime: object = _UNSET
        self._cached_secrets: list[str] = []

    def __call__(self) -> list[str]:
        try:
            mtime: object = self._store.path.stat().st_mtime
        except OSError:
            mtime = None
        if mtime != self._cached_mtime:
            env_keys = resolve_keys(settings=self._settings, store=None)
            file_keys = self._store.peek_keys()
            self._cached_secrets = [*env_keys.values(), *file_keys.values()]
            self._cached_mtime = mtime
        return self._cached_secrets


class SecretRedactionFilter(logging.Filter):
    """Replaces known secret values and key-shaped substrings with ``***``.

    Parameters
    ----------
    known_secrets : Iterable[str]
        Secret values to redact verbatim. Empty and falsy entries are
        ignored, so callers can pass a list with unset keys as ``None``.
    dynamic_secrets : Callable[[], Iterable[str]] | None
        Queried on every record for secret values not known at
        installation time (e.g. a key saved to `credentials.json` through
        the UI after the filter was attached).
    """

    def __init__(
        self,
        known_secrets: Iterable[str | None],
        dynamic_secrets: Callable[[], Iterable[str]] | None = None,
    ) -> None:
        super().__init__()
        self._known_secrets = [secret for secret in known_secrets if secret]
        self._dynamic_secrets = dynamic_secrets
        self._busy = threading.local()

    def _all_secrets(self) -> list[str]:
        if self._dynamic_secrets is None:
            return self._known_secrets
        extra = [secret for secret in self._dynamic_secrets() if secret]
        return [*self._known_secrets, *extra]

    def _redact(self, text: str) -> str:
        for secret in self._all_secrets():
            text = text.replace(secret, _REDACTED)
        for pattern in _KEY_PATTERNS:
            text = pattern.sub(_REDACTED, text)
        return text

    def _redact_message(self, record: logging.LogRecord) -> None:
        # Formatters such as uvicorn's AccessFormatter unpack record.args, so
        # the tuple keeps its shape and only string items are rewritten.
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                self._redact(arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        message = record.getMessage()
        if self._redact(message) != message:
            # A key inside a non-string argument: collapse to plain text.
            record.msg, record.args = self._redact(message), ()

    def filter(self, record: logging.LogRecord) -> bool:
        # Defense in depth: a record logged while this filter reads the keys
        # must not re-enter it (that recursion once stopped the app at start).
        if getattr(self._busy, "active", False):
            return True
        self._busy.active = True
        try:
            self._redact_and_format(record=record)
        finally:
            self._busy.active = False
        return True

    def _redact_and_format(self, record: logging.LogRecord) -> None:
        self._redact_message(record=record)
        if record.exc_info and not record.exc_text:
            formatted = logging.Formatter().formatException(record.exc_info)
            record.exc_text = self._redact(formatted)
        elif record.exc_text:
            record.exc_text = self._redact(record.exc_text)


def _secret_values(settings: Settings) -> list[str | None]:
    keys = (
        settings.groq_api_key,
        settings.gemini_api_key,
        settings.openai_api_key,
        settings.anthropic_api_key,
        settings.assemblyai_api_key,
    )
    return [key.get_secret_value() if key is not None else None for key in keys]


def _has_redaction_filter(handler: logging.Handler) -> bool:
    return any(isinstance(f, SecretRedactionFilter) for f in handler.filters)


def _build_dynamic_secret_source(
    settings: Settings,
) -> Callable[[], Iterable[str]] | None:
    try:
        config_dir: Path = resolve_config_dir(settings=settings, create=False)
    except (ConfigDirUnsafeError, OSError):
        # Keys saved from the UI (AssemblyAI has no recognizable prefix) would
        # then reach the logs unredacted: say so where the user can see it.
        logger.warning(
            "Redazione delle chiavi salvate disattivata: cartella di "
            "configurazione non risolvibile",
            exc_info=True,
        )
        return None
    store = CredentialStore(config_dir=config_dir)
    return _CachedKeyStoreSource(settings=settings, store=store)


def install_redaction(settings: Settings) -> None:
    """Attach a `SecretRedactionFilter` to every handler that could log a secret.

    Idempotent: a handler that already carries the filter is left alone, so
    calling this twice (e.g. once from `cli.py`, once from a test app) never
    duplicates redaction work. Also wires in a dynamic source over
    `credentials.json` so a key saved later through the UI (AssemblyAI has
    no recognizable prefix, so it would otherwise be invisible to
    `_KEY_PATTERNS`) is redacted from the next log line onward.
    """
    secrets = _secret_values(settings=settings)
    dynamic_secrets = _build_dynamic_secret_source(settings=settings)
    for name in _TARGET_LOGGER_NAMES:
        for handler in logging.getLogger(name).handlers:
            if not _has_redaction_filter(handler):
                handler.addFilter(
                    SecretRedactionFilter(
                        known_secrets=secrets, dynamic_secrets=dynamic_secrets
                    )
                )

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
from collections.abc import Iterable

from sbobina.settings import Settings

_REDACTED = "***"

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


class SecretRedactionFilter(logging.Filter):
    """Replaces known secret values and key-shaped substrings with ``***``.

    Parameters
    ----------
    known_secrets : Iterable[str]
        Secret values to redact verbatim. Empty and falsy entries are
        ignored, so callers can pass a list with unset keys as ``None``.
    """

    def __init__(self, known_secrets: Iterable[str | None]) -> None:
        super().__init__()
        self._known_secrets = [secret for secret in known_secrets if secret]

    def _redact(self, text: str) -> str:
        for secret in self._known_secrets:
            text = text.replace(secret, _REDACTED)
        for pattern in _KEY_PATTERNS:
            text = pattern.sub(_REDACTED, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(record.getMessage())
        record.args = None
        if record.exc_info and not record.exc_text:
            formatted = logging.Formatter().formatException(record.exc_info)
            record.exc_text = self._redact(formatted)
        elif record.exc_text:
            record.exc_text = self._redact(record.exc_text)
        return True


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


def install_redaction(settings: Settings) -> None:
    """Attach a `SecretRedactionFilter` to every handler that could log a secret.

    Idempotent: a handler that already carries the filter is left alone, so
    calling this twice (e.g. once from `cli.py`, once from a test app) never
    duplicates redaction work.
    """
    secrets = _secret_values(settings=settings)
    for name in _TARGET_LOGGER_NAMES:
        for handler in logging.getLogger(name).handlers:
            if not _has_redaction_filter(handler):
                handler.addFilter(SecretRedactionFilter(known_secrets=secrets))

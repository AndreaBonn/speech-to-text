"""Atomic, permission-checked storage for cloud provider API keys (D4).

`credentials.json` lives in the user config directory (`config_dir.py`),
never under `data_dir` (copied and shared with a course) or inside the
repository. Reading and writing never goes through `os.environ`: the
supervisor's `_child_env()` must be able to drop `SBOBINA_*_API_KEY` for
untrusted children (extraction, package import) without this store leaking
a key back in through the environment (S1).
"""

import json
import logging
import re
import sys
import threading
from pathlib import Path

from sbobina.atomic_json import atomic_write_json
from sbobina.settings import Settings

logger = logging.getLogger(__name__)

SECRET_PROVIDERS: tuple[str, ...] = (
    "groq",
    "gemini",
    "openai",
    "anthropic",
    "assemblyai",
)
MAX_KEY_LENGTH = 512
_FILE_MODE = 0o600
_LAST4_MIN_LENGTH = 12
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


class InvalidKeyError(ValueError):
    """A key or provider fails validation; the message never echoes the key."""


def _validate_provider(provider: str) -> str:
    if provider not in SECRET_PROVIDERS:
        raise InvalidKeyError(f"Provider sconosciuto: {provider}")
    return provider


def _validate_key(key: str) -> str:
    if not key:
        raise InvalidKeyError("La chiave non può essere vuota")
    if len(key) > MAX_KEY_LENGTH:
        raise InvalidKeyError(f"La chiave supera i {MAX_KEY_LENGTH} caratteri")
    if any(char.isspace() for char in key) or _CONTROL_CHAR_PATTERN.search(key):
        raise InvalidKeyError(
            "La chiave non può contenere spazi, a capo o caratteri di controllo"
        )
    return key


def _check_permissions(path: Path) -> None:
    if sys.platform == "win32":
        return
    mode = path.stat().st_mode & 0o777
    if mode != _FILE_MODE:
        path.chmod(_FILE_MODE)
        logger.warning(
            "credentials.json aveva permessi %o, corretti a %o", mode, _FILE_MODE
        )


def _read_raw(path: Path) -> dict[str, str]:
    if path.is_symlink():
        # chmod below would follow the link and change another file's mode.
        logger.warning("credentials.json è un symlink: ignorato")
        return {}
    if not path.exists():
        return {}
    _check_permissions(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as error:
        logger.warning("credentials.json illeggibile (%s), trattato come vuoto", error)
        return {}
    if not isinstance(raw, dict):
        logger.warning("credentials.json non è un oggetto JSON, trattato come vuoto")
        return {}
    return {key: value for key, value in raw.items() if isinstance(value, str)}


class CredentialStore:
    """Reads and writes `credentials.json` in a user config directory."""

    def __init__(self, config_dir: Path) -> None:
        self.path = config_dir / "credentials.json"
        # Read-modify-write: concurrent PUTs run in the threadpool.
        self._lock = threading.Lock()

    def get_keys(self) -> dict[str, str]:
        """Provider -> key, from the file only (no env override)."""
        return _read_raw(self.path)

    def peek_keys(self) -> dict[str, str]:
        """The keys without logging, chmod or symlink handling.

        For the log redaction filter: a warning logged while reading would
        pass through that same filter and read the file again, forever.
        """
        if self.path.is_symlink() or not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {key: value for key, value in raw.items() if isinstance(value, str)}

    def is_unreadable(self) -> bool:
        """True when a file exists but its keys cannot be read (A5).

        `get_keys` treats it as empty so the app keeps working; the Settings
        page must still tell "no key saved" apart from "saved keys lost".
        """
        if self.path.is_symlink():
            return True
        if not self.path.exists():
            return False
        try:
            raw = json.loads(self.path.read_text("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return True
        # A non-string value is a key the reader drops: lost all the same.
        return not isinstance(raw, dict) or not all(
            isinstance(value, str) for value in raw.values()
        )

    def set_key(self, provider: str, key: str) -> None:
        provider = _validate_provider(provider)
        key = _validate_key(key)
        with self._lock:
            data = self.get_keys()
            data[provider] = key
            atomic_write_json(path=self.path, data=data, mode=_FILE_MODE)

    def delete_key(self, provider: str) -> None:
        provider = _validate_provider(provider)
        with self._lock:
            data = self.get_keys()
            if provider in data:
                del data[provider]
                atomic_write_json(path=self.path, data=data, mode=_FILE_MODE)


def _settings_key(settings: Settings, provider: str) -> str | None:
    secret = getattr(settings, f"{provider}_api_key", None)
    return secret.get_secret_value() if secret is not None else None


def resolve_keys(settings: Settings, store: CredentialStore | None) -> dict[str, str]:
    """Provider -> key, env wins over the file (D4); no store means env only."""
    file_keys = store.get_keys() if store is not None else {}
    resolved: dict[str, str] = {}
    for provider in SECRET_PROVIDERS:
        env_value = _settings_key(settings=settings, provider=provider)
        if env_value:
            resolved[provider] = env_value
        elif provider in file_keys:
            resolved[provider] = file_keys[provider]
    return resolved


def masked_view(
    settings: Settings, store: CredentialStore | None
) -> dict[str, dict[str, str | bool | None]]:
    """Provider -> `{configured, last4, source}`; never the key itself."""
    file_keys = store.get_keys() if store is not None else {}
    view: dict[str, dict[str, str | bool | None]] = {}
    for provider in SECRET_PROVIDERS:
        env_value = _settings_key(settings=settings, provider=provider)
        if env_value:
            key, source = env_value, "env"
        elif provider in file_keys:
            key, source = file_keys[provider], "file"
        else:
            key, source = None, None
        view[provider] = {
            "configured": key is not None,
            "last4": key[-4:] if key and len(key) >= _LAST4_MIN_LENGTH else None,
            "source": source,
        }
    return view

"""Settings and keys as the running process must see them (T033).

`Settings` comes from env and `.env`; the user's choices saved from the UI
live in the config dir (`preferences.json`, `credentials.json`). Every entry
point (CLI, web requests, stage children) resolves both here, so a key or an
engine saved from the UI reaches the next job without a restart and without
ever passing through `os.environ` (S1).
"""

import logging

from sbobina.config_dir import ConfigDirUnsafeError, resolve_config_dir
from sbobina.credential_store import CredentialStore, resolve_keys
from sbobina.settings import Settings
from sbobina.user_preferences import effective_settings

logger = logging.getLogger(__name__)


def runtime_settings(settings: Settings) -> Settings:
    """`settings` with the engine and chain the user saved (env still wins)."""
    try:
        config_dir = resolve_config_dir(settings=settings, create=False)
    except ConfigDirUnsafeError:
        logger.warning("Cartella di configurazione non sicura: preferenze ignorate")
        return settings
    return effective_settings(settings=settings, config_dir=config_dir)


def runtime_keys(settings: Settings) -> dict[str, str]:
    """Provider -> key from env, then from `credentials.json`."""
    try:
        config_dir = resolve_config_dir(settings=settings, create=False)
    except ConfigDirUnsafeError:
        logger.warning("Cartella di configurazione non sicura: chiavi salvate ignorate")
        return resolve_keys(settings=settings, store=None)
    return resolve_keys(settings=settings, store=CredentialStore(config_dir=config_dir))

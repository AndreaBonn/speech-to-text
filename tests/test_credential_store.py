import logging
import stat
import sys
from pathlib import Path

import pytest
from pydantic import SecretStr

from sbobina.credential_store import (
    SECRET_PROVIDERS,
    CredentialStore,
    InvalidKeyError,
    masked_view,
    resolve_keys,
)
from sbobina.settings import Settings

SENTINEL = "sk-SENTINEL-0123456789abcdef"


def test_set_key_writes_the_file_with_mode_0600(tmp_path: Path) -> None:
    store = CredentialStore(config_dir=tmp_path)

    store.set_key(provider="groq", key=SENTINEL)

    mode = stat.S_IMODE(store.path.stat().st_mode)
    assert mode == 0o600
    assert store.get_keys() == {"groq": SENTINEL}


def test_set_key_rejects_an_unknown_provider(tmp_path: Path) -> None:
    store = CredentialStore(config_dir=tmp_path)

    with pytest.raises(InvalidKeyError):
        store.set_key(provider="mistral", key=SENTINEL)


def test_set_key_rejects_an_empty_key(tmp_path: Path) -> None:
    store = CredentialStore(config_dir=tmp_path)

    with pytest.raises(InvalidKeyError):
        store.set_key(provider="groq", key="")


@pytest.mark.parametrize(
    "bad_key",
    ["a" * 513, "has space", "has\nnewline", "has\x00control"],
)
def test_set_key_rejects_an_invalid_key_without_echoing_it(
    tmp_path: Path, bad_key: str
) -> None:
    store = CredentialStore(config_dir=tmp_path)

    with pytest.raises(InvalidKeyError) as excinfo:
        store.set_key(provider="groq", key=bad_key)

    assert bad_key not in str(excinfo.value)


def test_get_keys_on_a_file_with_wider_permissions_is_corrected_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    if sys.platform == "win32":
        pytest.skip("chmod non ha effetto su Windows")
    store = CredentialStore(config_dir=tmp_path)
    store.set_key(provider="groq", key=SENTINEL)
    store.path.chmod(0o644)

    with caplog.at_level(logging.WARNING):
        keys = store.get_keys()

    assert keys == {"groq": SENTINEL}
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert any("permess" in record.message for record in caplog.records)


def test_resolve_keys_env_wins_over_file(tmp_path: Path) -> None:
    store = CredentialStore(config_dir=tmp_path)
    store.set_key(provider="groq", key="from-file-0123456789")
    settings = Settings(groq_api_key=SecretStr(SENTINEL))

    resolved = resolve_keys(settings=settings, store=store)

    assert resolved["groq"] == SENTINEL


def test_resolve_keys_falls_back_to_file_without_env(tmp_path: Path) -> None:
    store = CredentialStore(config_dir=tmp_path)
    store.set_key(provider="groq", key="from-file-0123456789")
    settings = Settings()

    resolved = resolve_keys(settings=settings, store=store)

    assert resolved["groq"] == "from-file-0123456789"


def test_masked_view_reports_source_and_last4(tmp_path: Path) -> None:
    store = CredentialStore(config_dir=tmp_path)
    store.set_key(provider="groq", key="from-file-0123456789")
    settings = Settings(openai_api_key=SecretStr(SENTINEL))

    view = masked_view(settings=settings, store=store)

    assert view["groq"] == {"configured": True, "last4": "6789", "source": "file"}
    assert view["openai"]["source"] == "env"
    assert view["openai"]["last4"] == SENTINEL[-4:]
    assert view["anthropic"] == {"configured": False, "last4": None, "source": None}


def test_masked_view_omits_last4_below_twelve_characters(tmp_path: Path) -> None:
    store = CredentialStore(config_dir=tmp_path)
    store.set_key(provider="groq", key="short123")

    view = masked_view(settings=Settings(), store=store)

    assert view["groq"]["last4"] is None
    assert view["groq"]["configured"] is True


def test_delete_key_removes_it(tmp_path: Path) -> None:
    store = CredentialStore(config_dir=tmp_path)
    store.set_key(provider="groq", key=SENTINEL)

    store.delete_key(provider="groq")

    assert store.get_keys() == {}


def test_delete_key_on_a_missing_provider_is_a_no_op(tmp_path: Path) -> None:
    store = CredentialStore(config_dir=tmp_path)

    store.delete_key(provider="groq")

    assert store.get_keys() == {}


def test_get_keys_on_a_corrupted_file_warns_and_returns_empty_without_rewriting(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = CredentialStore(config_dir=tmp_path)
    store.path.write_text("{not json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        keys = store.get_keys()

    assert keys == {}
    assert store.path.read_text(encoding="utf-8") == "{not json"


def test_set_key_an_interrupted_write_leaves_the_previous_file_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = CredentialStore(config_dir=tmp_path)
    store.set_key(provider="groq", key="old-key-0123456789")

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated crash before replace")

    monkeypatch.setattr("sbobina.atomic_json.os.replace", _boom)
    with pytest.raises(RuntimeError):
        store.set_key(provider="groq", key="new-key-0123456789")

    assert store.get_keys() == {"groq": "old-key-0123456789"}
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


def test_set_key_refuses_to_write_through_a_symlink(tmp_path: Path) -> None:
    real_target = tmp_path / "elsewhere.json"
    real_target.write_text("{}", encoding="utf-8")
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    (config_dir / "credentials.json").symlink_to(real_target)
    store = CredentialStore(config_dir=config_dir)

    with pytest.raises(ValueError):
        store.set_key(provider="groq", key=SENTINEL)


def test_secret_providers_constant_covers_all_four_llm_providers_and_assemblyai() -> (
    None
):
    assert set(SECRET_PROVIDERS) == {
        "groq",
        "gemini",
        "openai",
        "anthropic",
        "assemblyai",
    }


def test_get_keys_symlinked_file_is_ignored_and_target_mode_untouched(
    tmp_path: Path,
) -> None:
    target = tmp_path / "elsewhere.json"
    target.write_text('{"groq": "gsk-from-link-0123456789"}', encoding="utf-8")
    target.chmod(0o644)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "credentials.json").symlink_to(target)

    keys = CredentialStore(config_dir=config_dir).get_keys()

    assert keys == {}
    assert target.stat().st_mode & 0o777 == 0o644


def test_get_keys_regular_file_is_read(tmp_path: Path) -> None:
    (tmp_path / "credentials.json").write_text(
        '{"groq": "gsk-regular-0123456789"}', encoding="utf-8"
    )

    assert CredentialStore(config_dir=tmp_path).get_keys() == {
        "groq": "gsk-regular-0123456789"
    }

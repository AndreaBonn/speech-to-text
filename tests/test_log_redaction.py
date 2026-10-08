import io
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import SecretStr

from sbobina.credential_store import CredentialStore
from sbobina.log_redaction import SecretRedactionFilter, install_redaction
from sbobina.settings import Settings

SENTINEL = "sk-SENTINEL-0123456789abcdef"


@pytest.fixture
def captured_root() -> Iterator[tuple[logging.Logger, io.StringIO, logging.Handler]]:
    """Root logger with a single StringIO handler, restored after the test.

    pytest's own log-capturing pushes a second handler onto root for the
    duration of the test call, so assertions on "the handler we installed"
    must use the returned handler, never `root.handlers` as a whole.
    """
    root = logging.getLogger()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream=stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    saved_handlers = root.handlers[:]
    saved_level = root.level
    root.handlers = [handler]
    root.setLevel(logging.DEBUG)
    try:
        yield root, stream, handler
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)


def test_install_redaction_masks_a_known_key_logged_with_args(
    captured_root: tuple[logging.Logger, io.StringIO, logging.Handler],
) -> None:
    root, stream, _handler = captured_root
    install_redaction(settings=Settings(groq_api_key=SecretStr(SENTINEL)))

    root.info("chiave %s", SENTINEL)

    output = stream.getvalue()
    assert SENTINEL not in output
    assert "***" in output


def test_install_redaction_leaves_a_message_without_keys_unchanged(
    captured_root: tuple[logging.Logger, io.StringIO, logging.Handler],
) -> None:
    root, stream, _handler = captured_root
    install_redaction(settings=Settings(groq_api_key=SecretStr(SENTINEL)))

    root.info("nessuna chiave qui, solo testo")

    assert stream.getvalue().strip() == "nessuna chiave qui, solo testo"


def test_install_redaction_redacts_a_traceback_containing_the_sentinel(
    captured_root: tuple[logging.Logger, io.StringIO, logging.Handler],
) -> None:
    root, stream, _handler = captured_root
    install_redaction(settings=Settings(groq_api_key=SecretStr(SENTINEL)))

    try:
        raise ValueError(f"401 Unauthorized: chiave {SENTINEL} non valida")
    except ValueError:
        root.exception("richiesta al provider fallita")

    output = stream.getvalue()
    assert SENTINEL not in output
    assert "***" in output


@pytest.mark.parametrize(
    "key_like",
    ["gsk_abcdefghijklmnopqrst", "AIzaSyAbCdEfGhIjKlMnOpQrStUvWx"],
)
def test_install_redaction_masks_key_shaped_text_even_without_a_known_value(
    captured_root: tuple[logging.Logger, io.StringIO, logging.Handler], key_like: str
) -> None:
    root, stream, _handler = captured_root
    install_redaction(settings=Settings())  # no keys configured

    root.info("risposta del provider: %s", key_like)

    output = stream.getvalue()
    assert key_like not in output
    assert "***" in output


def test_install_redaction_is_idempotent(
    captured_root: tuple[logging.Logger, io.StringIO, logging.Handler],
) -> None:
    _root, _stream, handler = captured_root
    install_redaction(settings=Settings(groq_api_key=SecretStr(SENTINEL)))
    install_redaction(settings=Settings(groq_api_key=SecretStr(SENTINEL)))

    redaction_filters = [
        f for f in handler.filters if isinstance(f, SecretRedactionFilter)
    ]
    assert len(redaction_filters) == 1


def test_install_redaction_redacts_records_propagated_from_a_child_logger(
    captured_root: tuple[logging.Logger, io.StringIO, logging.Handler],
) -> None:
    _root, stream, _handler = captured_root
    install_redaction(settings=Settings(groq_api_key=SecretStr(SENTINEL)))
    child = logging.getLogger("sbobina.some_module")
    child.setLevel(logging.DEBUG)

    child.info("chiave %s", SENTINEL)

    output = stream.getvalue()
    assert SENTINEL not in output
    assert "***" in output


# No recognizable prefix on purpose: unlike SENTINEL (sk-...), this must be
# caught only by the dynamic source, never by the static `_KEY_PATTERNS`
# regexes, so the two tests below cannot pass by accident.
UNPREFIXED_SENTINEL = "assemblyai-0123456789abcdef-no-known-prefix"


def test_install_redaction_redacts_a_key_saved_after_install(
    captured_root: tuple[logging.Logger, io.StringIO, logging.Handler],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AssemblyAI has no recognizable prefix, so a key saved via the UI into
    `credentials.json` after startup is only caught by the dynamic source,
    never by the static settings snapshot taken at `install_redaction` time.
    """
    root, stream, _handler = captured_root
    monkeypatch.setenv("SBOBINA_CONFIG_DIR", str(tmp_path))
    install_redaction(settings=Settings())
    store = CredentialStore(config_dir=tmp_path)
    store.set_key(provider="assemblyai", key=UNPREFIXED_SENTINEL)

    root.info("upload assemblyai con chiave %s", UNPREFIXED_SENTINEL)

    output = stream.getvalue()
    assert UNPREFIXED_SENTINEL not in output
    assert "***" in output


def test_install_redaction_dynamic_source_leaves_unrelated_text_unchanged(
    captured_root: tuple[logging.Logger, io.StringIO, logging.Handler],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positive case paired with the test above: redaction only touches the
    secret, not every log line, once a dynamic source is wired in."""
    root, stream, _handler = captured_root
    monkeypatch.setenv("SBOBINA_CONFIG_DIR", str(tmp_path))
    install_redaction(settings=Settings())
    store = CredentialStore(config_dir=tmp_path)
    store.set_key(provider="assemblyai", key=UNPREFIXED_SENTINEL)

    root.info("nessuna chiave qui, solo testo")

    assert stream.getvalue().strip() == "nessuna chiave qui, solo testo"


class _UnpackingFormatter(logging.Formatter):
    """Mirrors uvicorn's AccessFormatter, which unpacks record.args."""

    def formatMessage(self, record: logging.LogRecord) -> str:
        assert isinstance(record.args, tuple)
        client, path = record.args
        return f"{client} {path}"


def _filtered_record(*args: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s"',
        args=args,
        exc_info=None,
    )
    SecretRedactionFilter(known_secrets=[SENTINEL]).filter(record)
    return record


def test_filter_keeps_args_a_formatter_unpacks() -> None:
    record = _filtered_record("127.0.0.1:41336", "GET /impostazioni")

    assert _UnpackingFormatter().format(record) == "127.0.0.1:41336 GET /impostazioni"


def test_filter_redacts_a_key_inside_a_string_arg_keeping_the_tuple() -> None:
    record = _filtered_record("127.0.0.1:41336", f"GET /x?key={SENTINEL}")

    output = _UnpackingFormatter().format(record)

    assert SENTINEL not in output
    assert output.startswith("127.0.0.1:41336 GET /x?key=")


def test_install_redaction_with_a_corrupted_credentials_file_logs_without_recursion(
    tmp_path: Path,
    captured_root: tuple[logging.Logger, io.StringIO, logging.Handler],
) -> None:
    _root, stream, _handler = captured_root
    (tmp_path / "credentials.json").write_text("{broken", encoding="utf-8")
    install_redaction(settings=Settings(config_dir=tmp_path))

    logging.getLogger("sbobina.test").warning("avvio con chiavi illeggibili")

    assert "avvio con chiavi illeggibili" in stream.getvalue()


def test_filter_still_redacts_known_keys_in_a_record_nested_in_a_key_lookup() -> None:
    nested: list[logging.LogRecord] = []

    def source() -> list[str]:
        record = logging.LogRecord(
            "sbobina", logging.WARNING, __file__, 1, f"dentro {SENTINEL}", None, None
        )
        redaction.filter(record)
        nested.append(record)
        return []

    redaction = SecretRedactionFilter(known_secrets=[SENTINEL], dynamic_secrets=source)
    outer = logging.LogRecord("sbobina", logging.INFO, __file__, 1, "fuori", None, None)

    redaction.filter(outer)

    assert SENTINEL not in nested[0].getMessage()


@pytest.mark.parametrize(
    ("message", "args", "expected"),
    [
        pytest.param(
            "payload=%s count=%d",
            ({"key": SENTINEL}, 2),
            "payload={'key': '***'} count=2",
            id="dict-argument",
        ),
        pytest.param({"key": SENTINEL}, (), "{'key': '***'}", id="dict-message"),
    ],
)
def test_filter_non_string_values_redacts_formatted_message(
    message: object, args: tuple[object, ...], expected: str
) -> None:
    record = logging.LogRecord(
        name="sbobina",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=args,
        exc_info=None,
    )
    formatter = logging.Formatter(fmt="%(message)s")
    assert SENTINEL in formatter.format(record=record)

    accepted = SecretRedactionFilter(known_secrets=[]).filter(record=record)

    assert accepted is True
    assert formatter.format(record=record) == expected

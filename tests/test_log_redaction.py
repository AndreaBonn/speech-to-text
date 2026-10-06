import io
import logging
from collections.abc import Iterator

import pytest
from pydantic import SecretStr

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

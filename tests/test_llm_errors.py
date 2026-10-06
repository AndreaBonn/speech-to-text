import httpx
import pytest

from sbobina.correction import CorrectorUnavailableError
from sbobina.llm_errors import (
    ChainExhaustedError,
    FailureKind,
    ProviderUnavailableError,
    classify_http_failure,
    classify_transport_error,
)


@pytest.mark.parametrize("status", [401, 403])
def test_classify_http_failure_maps_auth_statuses(status: int) -> None:
    kind, retry_after_s = classify_http_failure(status=status, headers={})

    assert kind == FailureKind.AUTH
    assert retry_after_s is None


def test_classify_http_failure_maps_not_found_to_model_missing() -> None:
    kind, retry_after_s = classify_http_failure(status=404, headers={})

    assert kind == FailureKind.MODEL_MISSING
    assert retry_after_s is None


def test_classify_http_failure_maps_rate_limit_with_numeric_retry_after() -> None:
    kind, retry_after_s = classify_http_failure(
        status=429, headers={"Retry-After": "30"}
    )

    assert kind == FailureKind.RATE_LIMIT
    assert retry_after_s == 30.0


def test_classify_http_failure_maps_rate_limit_without_retry_after_header() -> None:
    kind, retry_after_s = classify_http_failure(status=429, headers={})

    assert kind == FailureKind.RATE_LIMIT
    assert retry_after_s is None


def test_classify_http_failure_maps_rate_limit_with_non_numeric_retry_after() -> None:
    kind, retry_after_s = classify_http_failure(
        status=429, headers={"Retry-After": "Wed, 21 Oct"}
    )

    assert kind == FailureKind.RATE_LIMIT
    assert retry_after_s is None


def test_classify_http_failure_maps_payment_required_to_quota() -> None:
    kind, retry_after_s = classify_http_failure(status=402, headers={})

    assert kind == FailureKind.QUOTA
    assert retry_after_s is None


@pytest.mark.parametrize("status", [400, 422])
def test_classify_http_failure_maps_bad_request_statuses(status: int) -> None:
    kind, retry_after_s = classify_http_failure(status=status, headers={})

    assert kind == FailureKind.BAD_REQUEST
    assert retry_after_s is None


@pytest.mark.parametrize("status", [500, 503, 529])
def test_classify_http_failure_maps_server_statuses(status: int) -> None:
    kind, retry_after_s = classify_http_failure(status=status, headers={})

    assert kind == FailureKind.SERVER
    assert retry_after_s is None


def test_classify_http_failure_raises_on_an_unmapped_status() -> None:
    with pytest.raises(ValueError, match="204"):
        classify_http_failure(status=204, headers={})


def test_classify_transport_error_maps_timeout() -> None:
    assert (
        classify_transport_error(httpx.ReadTimeout("timed out")) == FailureKind.TIMEOUT
    )


def test_classify_transport_error_maps_connection_errors_to_network() -> None:
    assert (
        classify_transport_error(httpx.ConnectError("refused")) == FailureKind.NETWORK
    )
    assert classify_transport_error(ConnectionError("down")) == FailureKind.NETWORK


def test_classify_transport_error_raises_on_an_unclassified_exception() -> None:
    with pytest.raises(TypeError):
        classify_transport_error(ValueError("not a transport error"))


def test_provider_unavailable_error_is_a_corrector_unavailable_error() -> None:
    error = ProviderUnavailableError(
        kind=FailureKind.RATE_LIMIT, provider="groq/llama", retry_after_s=30.0
    )

    assert isinstance(error, CorrectorUnavailableError)
    assert error.kind == FailureKind.RATE_LIMIT
    assert error.provider == "groq/llama"
    assert error.retry_after_s == 30.0


def test_provider_unavailable_error_busy_uses_the_italian_gpu_label() -> None:
    error = ProviderUnavailableError(
        kind=FailureKind.BUSY, provider="ollama", retry_after_s=None
    )

    assert "GPU occupata dalla trascrizione" in str(error)


def test_provider_unavailable_error_message_has_no_response_body() -> None:
    error = ProviderUnavailableError(
        kind=FailureKind.AUTH, provider="gemini/flash", retry_after_s=None
    )

    message = str(error)

    assert "gemini/flash" in message
    assert "chiave non valida" in message


def test_chain_exhausted_error_is_a_corrector_unavailable_error() -> None:
    causes = (
        ProviderUnavailableError(
            kind=FailureKind.RATE_LIMIT, provider="groq/llama", retry_after_s=30.0
        ),
        ProviderUnavailableError(
            kind=FailureKind.AUTH, provider="gemini/flash", retry_after_s=None
        ),
    )
    error = ChainExhaustedError(causes=causes)

    assert isinstance(error, CorrectorUnavailableError)
    assert error.causes == causes


def test_chain_exhausted_error_message_lists_every_cause_in_italian() -> None:
    causes = (
        ProviderUnavailableError(
            kind=FailureKind.RATE_LIMIT, provider="groq/llama", retry_after_s=30.0
        ),
        ProviderUnavailableError(
            kind=FailureKind.AUTH, provider="gemini/flash", retry_after_s=None
        ),
    )

    message = str(ChainExhaustedError(causes=causes))

    assert "groq/llama" in message
    assert "limite raggiunto" in message
    assert "gemini/flash" in message
    assert "chiave non valida" in message


def test_except_corrector_unavailable_error_catches_both_subclasses() -> None:
    for error in (
        ProviderUnavailableError(
            kind=FailureKind.NETWORK, provider="p/m", retry_after_s=None
        ),
        ChainExhaustedError(causes=()),
    ):
        try:
            raise error
        except CorrectorUnavailableError as caught:
            assert caught is error
        else:
            pytest.fail("expected CorrectorUnavailableError to be raised")

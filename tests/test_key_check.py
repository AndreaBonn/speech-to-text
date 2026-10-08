import httpx
import pytest

from sbobina.key_check import _check_assemblyai, check_key
from sbobina.llm_errors import FailureKind, ProviderUnavailableError

SENTINEL_KEY = "sk-SENTINEL-0123456789abcdef"


def _transport(status: int, seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json={"data": []})

    return httpx.MockTransport(handler)


def test_check_key_missing_key_makes_no_request() -> None:
    seen: list[httpx.Request] = []

    result = check_key(
        provider="groq", api_key=None, timeout_s=5, transport=_transport(200, seen)
    )

    assert result == "missing"
    assert seen == []


@pytest.mark.parametrize(
    ("status", "expected"), [(200, "ok"), (401, "auth"), (429, "limit"), (500, "error")]
)
def test_check_key_maps_the_provider_answer(status: int, expected: str) -> None:
    seen: list[httpx.Request] = []

    result = check_key(
        provider="openai",
        api_key=SENTINEL_KEY,
        timeout_s=5,
        transport=_transport(status, seen),
    )

    assert result == expected
    assert seen[0].url.path.endswith("/models")


def test_check_key_unreachable_provider_is_network() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    result = check_key(
        provider="anthropic",
        api_key=SENTINEL_KEY,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )

    assert result == "network"


def test_check_key_assemblyai_sends_the_key_in_the_header_only() -> None:
    seen: list[httpx.Request] = []

    result = check_key(
        provider="assemblyai",
        api_key=SENTINEL_KEY,
        timeout_s=5,
        transport=_transport(200, seen),
    )

    assert result == "ok"
    assert seen[0].headers["authorization"] == SENTINEL_KEY
    assert SENTINEL_KEY not in str(seen[0].url)


@pytest.mark.parametrize(
    ("error_type", "expected"),
    [
        (httpx.ConnectError, FailureKind.NETWORK),
        (httpx.ReadTimeout, FailureKind.TIMEOUT),
    ],
)
def test_check_assemblyai_transport_failure_preserves_kind(
    error_type: type[httpx.TransportError], expected: FailureKind
) -> None:
    failure = error_type("connection failed")

    def handler(request: httpx.Request) -> httpx.Response:
        raise failure

    transport = httpx.MockTransport(handler=handler)
    with pytest.raises(ProviderUnavailableError) as excinfo:
        _check_assemblyai(api_key=SENTINEL_KEY, timeout_s=5, transport=transport)

    assert excinfo.value.kind == expected
    assert excinfo.value.provider == "assemblyai"
    assert excinfo.value.retry_after_s is None
    assert excinfo.value.__cause__ is failure
    assert (
        check_key(
            provider="assemblyai",
            api_key=SENTINEL_KEY,
            timeout_s=5,
            transport=transport,
        )
        == "network"
    )


@pytest.mark.parametrize(
    ("status", "expected", "retry_after", "result"),
    [
        (401, FailureKind.AUTH, None, "auth"),
        (429, FailureKind.RATE_LIMIT, 23.0, "limit"),
    ],
)
def test_check_assemblyai_http_failure_preserves_kind_and_retry(
    status: int, expected: FailureKind, retry_after: float | None, result: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=status, headers={"Retry-After": "23"})

    transport = httpx.MockTransport(handler=handler)
    with pytest.raises(ProviderUnavailableError) as excinfo:
        _check_assemblyai(api_key=SENTINEL_KEY, timeout_s=5, transport=transport)

    assert excinfo.value.kind == expected
    assert excinfo.value.provider == "assemblyai"
    assert excinfo.value.retry_after_s == retry_after
    assert (
        check_key(
            provider="assemblyai",
            api_key=SENTINEL_KEY,
            timeout_s=5,
            transport=transport,
        )
        == result
    )

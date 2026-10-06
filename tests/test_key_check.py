import httpx
import pytest

from sbobina.key_check import check_key

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

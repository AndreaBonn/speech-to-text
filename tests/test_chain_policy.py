import pytest

from sbobina.chain_policy import LinkState
from sbobina.llm_errors import FailureKind


def test_fresh_link_is_eligible() -> None:
    assert LinkState().eligible(now=0.0) is True


@pytest.mark.parametrize(
    "kind",
    [FailureKind.AUTH, FailureKind.MISSING_KEY, FailureKind.MODEL_MISSING],
)
def test_record_failure_disables_the_link_forever_on_permanent_kinds(
    kind: FailureKind,
) -> None:
    state = LinkState().record_failure(kind=kind, retry_after_s=None, now=0.0)

    assert state.eligible(now=0.0) is False
    assert state.eligible(now=1_000_000.0) is False


def test_record_failure_disables_the_link_forever_on_bad_request() -> None:
    state = LinkState().record_failure(
        kind=FailureKind.BAD_REQUEST, retry_after_s=None, now=0.0
    )

    assert state.eligible(now=0.0) is False
    assert state.eligible(now=1_000_000.0) is False


def test_record_failure_rate_limit_uses_the_given_retry_after() -> None:
    state = LinkState().record_failure(
        kind=FailureKind.RATE_LIMIT, retry_after_s=30.0, now=0.0
    )

    assert state.eligible(now=29.0) is False
    assert state.eligible(now=30.0) is True


def test_record_failure_rate_limit_without_retry_after_uses_default_60s() -> None:
    state = LinkState().record_failure(
        kind=FailureKind.RATE_LIMIT, retry_after_s=None, now=0.0
    )

    assert state.eligible(now=59.0) is False
    assert state.eligible(now=60.0) is True


def test_record_failure_quota_uses_the_same_cooldown_rule_as_rate_limit() -> None:
    state = LinkState().record_failure(
        kind=FailureKind.QUOTA, retry_after_s=None, now=10.0
    )

    assert state.eligible(now=69.0) is False
    assert state.eligible(now=70.0) is True


@pytest.mark.parametrize(
    "kind", [FailureKind.TIMEOUT, FailureKind.SERVER, FailureKind.NETWORK]
)
def test_three_consecutive_connectivity_failures_cool_down_for_120s(
    kind: FailureKind,
) -> None:
    state = LinkState()
    for _ in range(3):
        state = state.record_failure(kind=kind, retry_after_s=None, now=0.0)

    assert state.eligible(now=119.0) is False
    assert state.eligible(now=120.0) is True


def test_two_connectivity_failures_do_not_cool_down_the_link() -> None:
    state = LinkState()
    for _ in range(2):
        state = state.record_failure(
            kind=FailureKind.TIMEOUT, retry_after_s=None, now=0.0
        )

    assert state.eligible(now=0.0) is True


def test_record_success_resets_the_connectivity_counter() -> None:
    state = LinkState()
    for _ in range(2):
        state = state.record_failure(
            kind=FailureKind.TIMEOUT, retry_after_s=None, now=0.0
        )
    state = state.record_success()
    for _ in range(2):
        state = state.record_failure(
            kind=FailureKind.TIMEOUT, retry_after_s=None, now=0.0
        )

    # 2 + success-reset + 2 more: only 2 consecutive failures since the
    # reset, so the link is still eligible.
    assert state.eligible(now=0.0) is True


def test_three_consecutive_invalid_responses_exclude_the_link_forever() -> None:
    state = LinkState()
    for _ in range(3):
        state = state.record_invalid()

    assert state.eligible(now=0.0) is False
    assert state.eligible(now=1_000_000.0) is False


def test_two_invalid_responses_then_one_valid_does_not_exclude_the_link() -> None:
    state = LinkState().record_invalid().record_invalid().record_success()

    assert state.eligible(now=0.0) is True


def test_record_success_does_not_re_enable_a_disabled_link() -> None:
    state = LinkState().record_failure(
        kind=FailureKind.AUTH, retry_after_s=None, now=0.0
    )

    state = state.record_success()

    assert state.eligible(now=0.0) is False


def test_link_state_is_immutable() -> None:
    state = LinkState()

    new_state = state.record_failure(kind=FailureKind.AUTH, retry_after_s=None, now=0.0)

    assert state.eligible(now=0.0) is True
    assert new_state.eligible(now=0.0) is False
    assert state is not new_state

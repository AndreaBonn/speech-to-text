"""Eligibility policy for one link of the LLM fallback chain.

Pure and clock-injected: every method returns a new `LinkState` instead of
mutating, so the caller owns thread-safety and the wall clock.
"""

from dataclasses import dataclass, replace

from sbobina.llm_errors import FailureKind

_DEFAULT_COOLDOWN_S = 60.0
_CONNECTIVITY_FAILURE_THRESHOLD = 3
_CONNECTIVITY_COOLDOWN_S = 120.0
_INVALID_RESPONSE_THRESHOLD = 3

# auth/missing_key/model_missing: the credential or the model will not
# change mid-chain. bad_request: a rejected model/parameter repeats on
# every chunk, so retrying it is never useful for this chain.
_PERMANENT_KINDS = frozenset(
    {
        FailureKind.AUTH,
        FailureKind.MISSING_KEY,
        FailureKind.MODEL_MISSING,
        FailureKind.BAD_REQUEST,
    }
)
# rate_limit/quota: the provider names a cooldown (or none, default 60s).
_COOLDOWN_KINDS = frozenset({FailureKind.RATE_LIMIT, FailureKind.QUOTA})
# timeout/server/network: transient connectivity issues, tolerated twice.
_CONNECTIVITY_KINDS = frozenset(
    {FailureKind.TIMEOUT, FailureKind.SERVER, FailureKind.NETWORK}
)


@dataclass(frozen=True)
class LinkState:
    """Eligibility state for one chain link."""

    disabled: bool = False
    cooldown_until: float | None = None
    consecutive_connectivity_failures: int = 0
    consecutive_invalid_responses: int = 0

    def eligible(self, now: float) -> bool:
        if self.disabled:
            return False
        return self.cooldown_until is None or now >= self.cooldown_until

    def record_failure(
        self, kind: FailureKind, retry_after_s: float | None, now: float
    ) -> "LinkState":
        if kind in _PERMANENT_KINDS:
            return replace(self, disabled=True)
        if kind in _COOLDOWN_KINDS:
            cooldown = (
                retry_after_s if retry_after_s is not None else _DEFAULT_COOLDOWN_S
            )
            return replace(self, cooldown_until=now + cooldown)
        if kind in _CONNECTIVITY_KINDS:
            return self._record_connectivity_failure(now=now)
        raise ValueError(f"Unhandled failure kind: {kind}")

    def _record_connectivity_failure(self, now: float) -> "LinkState":
        failures = self.consecutive_connectivity_failures + 1
        if failures < _CONNECTIVITY_FAILURE_THRESHOLD:
            return replace(self, consecutive_connectivity_failures=failures)
        return replace(
            self,
            cooldown_until=now + _CONNECTIVITY_COOLDOWN_S,
            consecutive_connectivity_failures=0,
        )

    def record_invalid(self) -> "LinkState":
        invalid = self.consecutive_invalid_responses + 1
        if invalid < _INVALID_RESPONSE_THRESHOLD:
            return replace(self, consecutive_invalid_responses=invalid)
        return replace(self, disabled=True)

    def record_success(self) -> "LinkState":
        return replace(
            self,
            consecutive_connectivity_failures=0,
            consecutive_invalid_responses=0,
        )

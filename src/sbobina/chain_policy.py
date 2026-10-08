"""Eligibility policy for one link of the LLM fallback chain.

Pure and clock-injected: every method returns a new `LinkState` instead of
mutating, so the caller owns thread-safety and the wall clock.
"""

from dataclasses import dataclass, replace
from typing import assert_never

from sbobina.llm_errors import FailureKind

_DEFAULT_COOLDOWN_S = 60.0
# The Ollama link only turns busy while the supervisor holds the GPU for
# transcription (gpu_lock.py): a much shorter, dedicated default than the
# provider-quota cooldown, since the lease is typically seconds, not minutes.
_BUSY_COOLDOWN_S = 30.0
_CONNECTIVITY_FAILURE_THRESHOLD = 3
_CONNECTIVITY_COOLDOWN_S = 120.0
_INVALID_RESPONSE_THRESHOLD = 3

# rate_limit/quota: the provider names a cooldown (or none, default 60s).
# busy: the GPU guard never names one, so it always falls back to its own
# default below.
_COOLDOWN_DEFAULTS_S: dict[FailureKind, float] = {
    FailureKind.RATE_LIMIT: _DEFAULT_COOLDOWN_S,
    FailureKind.QUOTA: _DEFAULT_COOLDOWN_S,
    FailureKind.BUSY: _BUSY_COOLDOWN_S,
}


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
        # Spelled out per member so mypy rejects a FailureKind left unclassified.
        match kind:
            # The credential or the model will not change mid-chain; a rejected
            # model/parameter repeats on every chunk, so retrying never helps.
            case (
                FailureKind.AUTH
                | FailureKind.MISSING_KEY
                | FailureKind.MODEL_MISSING
                | FailureKind.BAD_REQUEST
            ):
                return replace(self, disabled=True)
            case FailureKind.RATE_LIMIT | FailureKind.QUOTA | FailureKind.BUSY:
                cooldown = (
                    retry_after_s
                    if retry_after_s is not None
                    else _COOLDOWN_DEFAULTS_S[kind]
                )
                return replace(self, cooldown_until=now + cooldown)
            # Transient connectivity issues, tolerated twice.
            case FailureKind.TIMEOUT | FailureKind.SERVER | FailureKind.NETWORK:
                return self._record_connectivity_failure(now=now)
            case _ as unhandled:
                assert_never(unhandled)

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

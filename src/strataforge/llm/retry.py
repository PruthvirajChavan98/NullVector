"""Retry classification and deterministic backoff for the Phase 03 gateway."""

from __future__ import annotations

from nullvector.llm.types import GatewayFailureCategory, GatewayRetryPolicy

RETRYABLE_FAILURE_CATEGORIES = {
    GatewayFailureCategory.TIMEOUT,
    GatewayFailureCategory.RATE_LIMIT,
    GatewayFailureCategory.NETWORK_FAILURE,
    GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE,
}


def is_retryable(category: GatewayFailureCategory) -> bool:
    """Return whether a failure category is retryable by policy."""

    return category in RETRYABLE_FAILURE_CATEGORIES


def backoff_delay_seconds(policy: GatewayRetryPolicy, *, attempt_number: int) -> float:
    """Compute deterministic exponential backoff without jitter."""

    exponent = max(attempt_number - 1, 0)
    base = policy.initial_backoff_seconds * (policy.backoff_multiplier**exponent)
    return min(base, policy.max_backoff_seconds)


def should_retry(
    category: GatewayFailureCategory,
    *,
    attempt_number: int,
    policy: GatewayRetryPolicy,
) -> bool:
    """Return whether the gateway should schedule another attempt."""

    return is_retryable(category) and attempt_number < policy.max_attempts

"""Unit tests for gateway circuit-breaker state transitions."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from nullvector.llm.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState


class FakeClock:
    """Deterministic monotonic clock for circuit-breaker tests."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_circuit_breaker_transitions_closed_open_half_open_and_closed() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(
        CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout_seconds=10.0,
            half_open_max_calls=1,
        ),
        time_fn=clock,
    )

    assert breaker.allow_request() is True
    breaker.record_failure()
    assert breaker.state == CircuitState.CLOSED

    breaker.record_failure()
    reopened_state: CircuitState = breaker.state
    assert reopened_state is CircuitState.OPEN
    assert breaker.allow_request() is False

    clock.advance(10.0)
    assert breaker.allow_request() is True
    half_open_state: CircuitState = breaker.state
    assert half_open_state is CircuitState.HALF_OPEN
    assert breaker.allow_request() is False

    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0
    assert breaker.allow_request() is True


def test_circuit_breaker_reopens_when_half_open_probe_fails() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(
        CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout_seconds=5.0,
            half_open_max_calls=1,
        ),
        time_fn=clock,
    )

    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN

    clock.advance(5.0)
    assert breaker.allow_request() is True
    half_open_state: CircuitState = breaker.state
    assert half_open_state is CircuitState.HALF_OPEN

    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN
    assert breaker.allow_request() is False


def test_circuit_breaker_record_failure_is_thread_safe() -> None:
    breaker = CircuitBreaker(
        CircuitBreakerConfig(
            failure_threshold=5,
            recovery_timeout_seconds=30.0,
            half_open_max_calls=1,
        )
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = tuple(executor.submit(breaker.record_failure) for _ in range(20))
        for future in futures:
            future.result()

    assert breaker.state == CircuitState.OPEN
    assert breaker.failure_count == 5

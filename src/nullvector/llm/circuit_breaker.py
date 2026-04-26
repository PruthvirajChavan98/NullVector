"""Thread-safe circuit breaker primitives for gateway model fallbacks."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from enum import StrEnum

from pydantic import PositiveFloat, PositiveInt

from nullvector.domain.common import NullVectorModel


class CircuitBreakerConfig(NullVectorModel):
    """Static configuration for one gateway circuit breaker."""

    failure_threshold: PositiveInt = 5
    recovery_timeout_seconds: PositiveFloat = 30.0
    half_open_max_calls: PositiveInt = 1


class CircuitState(StrEnum):
    """Finite-state machine used by the gateway circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Thread-safe circuit breaker for one logical upstream model."""

    def __init__(
        self,
        config: CircuitBreakerConfig,
        *,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._time_fn = time_fn
        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        """Return the current breaker state."""

        with self._lock:
            return self._state

    @property
    def failure_count(self) -> int:
        """Return the current consecutive failure count."""

        with self._lock:
            return self._failure_count

    def allow_request(self) -> bool:
        """Return whether one request may proceed under the current state."""

        with self._lock:
            if self._state is CircuitState.CLOSED:
                return True

            if self._state is CircuitState.OPEN:
                if not self._recovery_window_elapsed():
                    return False
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0

            if self._half_open_calls >= self._config.half_open_max_calls:
                return False
            self._half_open_calls += 1
            return True

    def record_success(self) -> None:
        """Close the circuit and reset counters after a healthy call."""

        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None
            self._half_open_calls = 0

    def record_failure(self) -> None:
        """Increment failures and open the circuit when the threshold is crossed."""

        with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                self._trip_open()
                return
            if self._state is CircuitState.OPEN:
                # Already open — do not restart the recovery window.
                return

            self._failure_count += 1
            if self._failure_count >= self._config.failure_threshold:
                self._trip_open()

    def _recovery_window_elapsed(self) -> bool:
        """Return whether the open timeout has elapsed."""

        if self._opened_at is None:
            return True
        return (self._time_fn() - self._opened_at) >= self._config.recovery_timeout_seconds

    def _trip_open(self) -> None:
        """Transition the breaker to OPEN and mark the opening time."""

        self._state = CircuitState.OPEN
        self._failure_count = self._config.failure_threshold
        self._opened_at = self._time_fn()
        self._half_open_calls = 0


__all__ = [
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
]

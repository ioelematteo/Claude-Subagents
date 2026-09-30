"""Reference implementation of a token-bucket rate limiter with an injected clock."""

from __future__ import annotations

from typing import Callable


class TokenBucket:
    """Token bucket that refills lazily from a caller-supplied clock."""

    def __init__(self, rate: float, capacity: float, clock: Callable[[], float]) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self._rate = float(rate)
        self._capacity = float(capacity)
        self._clock = clock
        self._tokens = float(capacity)
        self._last = clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = now - self._last
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last = now

    def allow(self, cost: float = 1.0) -> bool:
        """Consume `cost` tokens and return True if the bucket can pay for them."""
        if cost <= 0:
            raise ValueError("cost must be > 0")
        self._refill()
        if cost > self._capacity:
            return False
        if self._tokens >= cost:
            self._tokens -= cost
            return True
        return False

    @property
    def tokens(self) -> float:
        """Current token count after accounting for elapsed time."""
        self._refill()
        return self._tokens

"""Layer 3: a pool of API keys for one provider, used round-robin with health tracking.

Each request takes the pool's keys in rotation order, starting one further along each time,
so load spreads evenly over every key. A key that hits a rate limit (HTTP 429) rests for
KEY_COOLDOWN_S seconds, or the server's retry-after when it sends one, and the request moves
straight on to the next key: the switch is an in-memory step, no waiting. A key the provider
refuses (401/403) rests for ROUTER_BROKEN_COOLDOWN_S. Latency is tracked per key as a moving
average, for the faculty page. Thread-safe: the API serves requests from a thread pool.
Keys never leave this object unmasked.
"""

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from piq.config import KEY_COOLDOWN_S, KEY_LATENCY_WEIGHT, ROUTER_BROKEN_COOLDOWN_S


def mask(key: str) -> str:
    """'gsk_…9f2c': enough to tell keys apart in a status line, never enough to use one."""
    return f"{key[:4]}…{key[-4:]}" if len(key) > 10 else "…"


@dataclass
class _Health:
    cooldown_until: float = 0.0
    reason: str = ""
    latency_s: float | None = None  # moving average
    successes: int = 0
    rate_limits: int = 0
    failures: int = 0


@dataclass(frozen=True)
class KeyStatus:
    key: str  # masked
    available: bool
    rests_for_s: float
    reason: str
    latency_ms: int | None
    successes: int
    rate_limits: int


class KeyPoolManager:
    def __init__(
        self,
        keys: Sequence[str],
        cooldown: float = KEY_COOLDOWN_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.keys = tuple(dict.fromkeys(k for k in keys if k))
        self.cooldown, self._clock = cooldown, clock
        self._lock = threading.Lock()
        self._next = 0
        self._health = {k: _Health() for k in self.keys}

    def __len__(self) -> int:
        return len(self.keys)

    def _available(self, key: str, now: float) -> bool:
        return self._health[key].cooldown_until <= now

    def order(self) -> list[str]:
        """The keys to try for one request: every available key in rotation order, starting
        one further along than the last request did. [] when every key is resting."""
        with self._lock:
            now = self._clock()
            n = len(self.keys)
            ring = [self.keys[(self._next + i) % n] for i in range(n)]
            if n:
                self._next = (self._next + 1) % n
            return [k for k in ring if self._available(k, now)]

    def success(self, key: str, latency_s: float) -> None:
        with self._lock:
            h = self._health[key]
            h.successes += 1
            h.cooldown_until, h.reason = 0.0, ""
            w = KEY_LATENCY_WEIGHT
            h.latency_s = (
                latency_s if h.latency_s is None else (1 - w) * h.latency_s + w * latency_s
            )

    def rate_limited(self, key: str, retry_after: float | None = None) -> None:
        """Rest the key for the server's retry-after, or KEY_COOLDOWN_S without one."""
        with self._lock:
            h = self._health[key]
            h.rate_limits += 1
            h.cooldown_until = self._clock() + (retry_after or self.cooldown)
            h.reason = "rate limited"

    def refused(self, key: str, reason: str = "refused") -> None:
        """A key the provider rejects (bad or revoked): rest it for an hour."""
        with self._lock:
            h = self._health[key]
            h.failures += 1
            h.cooldown_until = self._clock() + ROUTER_BROKEN_COOLDOWN_S
            h.reason = reason

    def retry_in(self) -> float:
        """Seconds until the first resting key is available again (0 if one already is)."""
        with self._lock:
            now = self._clock()
            waits = [max(0.0, h.cooldown_until - now) for h in self._health.values()]
            return min(waits, default=0.0)

    def available_count(self) -> int:
        with self._lock:
            now = self._clock()
            return sum(self._available(k, now) for k in self.keys)

    def status(self) -> list[KeyStatus]:
        with self._lock:
            now = self._clock()
            return [
                KeyStatus(
                    mask(k),
                    self._available(k, now),
                    max(0.0, h.cooldown_until - now),
                    h.reason,
                    None if h.latency_s is None else round(h.latency_s * 1000),
                    h.successes,
                    h.rate_limits,
                )
                for k, h in self._health.items()
            ]

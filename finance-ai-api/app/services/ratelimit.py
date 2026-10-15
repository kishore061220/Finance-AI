"""A tiny, dependency-free in-process rate limiter.

The assistant is the one endpoint that can reach an external, paid provider, so
it is the one that needs a cap: without it a single client could run up cost or
exhaust a provider quota. A full distributed limiter (Redis / gateway) is the
right long-term answer, but that adds an infrastructure dependency this project
does not have. This fixed-window limiter is deliberately small and honest about
its scope:

* state is **per process** - behind multiple workers or replicas each holds its
  own counter, so the effective limit is ``max_requests * replicas``. It is a
  safety valve, not a billing-grade quota.
* it is keyed by an opaque string (the caller's user id), so one user cannot
  consume another's budget.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Deque, Dict, Optional


class FixedWindowLimiter:
    """Allow at most ``max_requests`` per ``window_seconds`` for a given key."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # monotonic timestamps of the accepted hits still inside the window
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, now: Optional[float] = None) -> bool:
        """Record a hit for ``key`` and report whether it is within budget."""
        moment = time.monotonic() if now is None else now
        cutoff = moment - self.window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.max_requests:
                return False
            hits.append(moment)
            return True

    def reset(self) -> None:
        """Forget every key. Used by tests so they never leak state."""
        with self._lock:
            self._hits.clear()


# 30 questions per minute per user is far above human typing speed while still
# capping a runaway client.
assistant_limiter = FixedWindowLimiter(max_requests=30, window_seconds=60.0)

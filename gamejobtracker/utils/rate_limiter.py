"""Simple rate limiter for API calls."""

import random
import time
from collections import defaultdict


class RateLimiter:
    """Token-bucket style rate limiter with jitter."""

    def __init__(self, calls_per_minute: int = 10, jitter_range: tuple[float, float] = (0.5, 2.0)):
        self._min_interval = 60.0 / calls_per_minute
        self._jitter_range = jitter_range
        self._last_call: dict[str, float] = defaultdict(float)

    def wait(self, key: str = "default") -> None:
        """Block until it's safe to make the next call for the given key."""
        elapsed = time.time() - self._last_call[key]
        wait_time = self._min_interval - elapsed
        if wait_time > 0:
            jitter = random.uniform(*self._jitter_range)
            time.sleep(wait_time + jitter)
        self._last_call[key] = time.time()

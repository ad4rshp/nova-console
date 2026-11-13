import os
import threading
import time
from collections import defaultdict, deque
from typing import Optional

class SlidingWindowRateLimiter:
    """
    Thread-safe sliding-window in-memory rate limiter per client IP.
    """

    def __init__(self, default_limit: int = 60, window_seconds: float = 60.0):
        self.default_limit = default_limit
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check_rate_limit(
        self,
        client_ip: str,
        limit: Optional[int] = None
    ) -> tuple[bool, int, float]:
        """
        Checks if the client IP is within rate limits.
        Returns:
            (allowed: bool, remaining: int, retry_after: float)
        """
        max_requests = limit if limit is not None else int(os.environ.get("NOVA_RATE_LIMIT_PER_MINUTE", str(self.default_limit)))
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            q = self._requests[client_ip]
            # Prune timestamps older than window
            while q and q[0] < cutoff:
                q.popleft()

            if len(q) >= max_requests:
                earliest = q[0]
                retry_after = max(1.0, round(self.window_seconds - (now - earliest), 1))
                return False, 0, retry_after

            q.append(now)
            remaining = max(0, max_requests - len(q))
            return True, remaining, 0.0

    def reset(self):
        with self._lock:
            self._requests.clear()

# Global default rate limiter instance (60 req/min)
global_rate_limiter = SlidingWindowRateLimiter(default_limit=60, window_seconds=60.0)

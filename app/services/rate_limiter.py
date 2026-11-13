import os
import threading
import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    """
    Thread-safe bounded sliding-window in-memory rate limiter per client IP and category.
    """

    CATEGORY_DEFAULTS = {
        "proxy": 120,
        "chat": 60,
        "admin": 30,
        "default": 60,
    }

    def __init__(self, default_limit: int = 60, window_seconds: float = 60.0, max_tracked_keys: int = 10000):
        self.default_limit = default_limit
        self.window_seconds = window_seconds
        self.max_tracked_keys = max_tracked_keys
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._last_active: dict[str, float] = {}
        self._lock = threading.Lock()

    def _get_category_limit(self, category: str, explicit_limit: int | None = None) -> int:
        if explicit_limit is not None:
            return explicit_limit

        env_var = f"NOVA_RATE_LIMIT_{category.upper()}"
        if env_var in os.environ:
            try:
                return int(os.environ[env_var])
            except ValueError:
                pass

        if "NOVA_RATE_LIMIT_PER_MINUTE" in os.environ:
            try:
                return int(os.environ["NOVA_RATE_LIMIT_PER_MINUTE"])
            except ValueError:
                pass

        return self.CATEGORY_DEFAULTS.get(category.lower(), self.default_limit)

    def _prune_expired_locked(self, now: float, cutoff: float) -> None:
        """Removes empty deques and stale IP tracking to prevent memory exhaustion."""
        to_delete = [
            key for key, q in self._requests.items()
            if not q or q[-1] < cutoff
        ]
        for key in to_delete:
            self._requests.pop(key, None)
            self._last_active.pop(key, None)

        # If still over capacity, drop the oldest keys by last activity
        if len(self._requests) > self.max_tracked_keys:
            sorted_keys = sorted(self._last_active.items(), key=lambda item: item[1])
            excess = len(self._requests) - self.max_tracked_keys
            for key, _ in sorted_keys[:excess]:
                self._requests.pop(key, None)
                self._last_active.pop(key, None)

    def check_rate_limit(
        self,
        client_ip: str,
        limit: int | None = None,
        category: str = "default"
    ) -> tuple[bool, int, float]:
        """
        Checks if client IP is within rate limits for the given category.
        Returns:
            (allowed: bool, remaining: int, retry_after: float)
        """
        max_requests = self._get_category_limit(category, limit)
        now = time.time()
        cutoff = now - self.window_seconds
        key = f"{client_ip}:{category.lower()}"

        with self._lock:
            # Periodic cleanup when table grows large
            if len(self._requests) > self.max_tracked_keys:
                self._prune_expired_locked(now, cutoff)

            q = self._requests[key]
            while q and q[0] < cutoff:
                q.popleft()

            if len(q) >= max_requests:
                earliest = q[0]
                retry_after = max(1.0, round(self.window_seconds - (now - earliest), 1))
                return False, 0, retry_after

            q.append(now)
            self._last_active[key] = now
            remaining = max(0, max_requests - len(q))
            return True, remaining, 0.0

    def reset(self):
        with self._lock:
            self._requests.clear()
            self._last_active.clear()


# Global default rate limiter instance
global_rate_limiter = SlidingWindowRateLimiter(default_limit=60, window_seconds=60.0)

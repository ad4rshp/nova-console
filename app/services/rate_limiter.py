import os
import threading
import time
from collections import defaultdict, deque
from typing import Any


class RateLimitResult(tuple):
    """
    Subclass of 3-tuple (allowed, remaining, retry_after) for 100% backward compatibility,
    with named attribute access and .limit metadata.
    """
    def __new__(cls, allowed: bool, remaining: int, retry_after: float, limit: int = 60):
        instance = super().__new__(cls, (allowed, remaining, retry_after))
        instance.allowed = allowed
        instance.remaining = remaining
        instance.retry_after = retry_after
        instance.limit = limit
        return instance


class SlidingWindowRateLimiter:
    """
    Thread-safe bounded sliding-window in-memory rate limiter.
    Supports granular limits by endpoint category, client IP, or authenticated token/user.
    Provides standard rate-limit headers (X-RateLimit-Limit, X-RateLimit-Remaining, Retry-After).
    """

    CATEGORY_DEFAULTS = {
        "dashboard": 30,
        "history": 20,
        "settings": 10,
        "models": 20,
        "chat": 5,
        "terminal": 5,
        "proxy": 120,
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

    def _get_category_limit(self, category: str, explicit_limit: int | None = None, is_local: bool = False) -> int:
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

        base = self.CATEGORY_DEFAULTS.get(category.lower(), self.default_limit)
        # Relax limits for unexposed single-user localhost deployments to avoid throttling UI polling
        if is_local and not os.environ.get("NOVA_STRICT_RATE_LIMIT"):
            return max(base, base * 4)

        return base

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
        identifier: str,
        limit: int | None = None,
        category: str = "default",
        is_local: bool = False
    ) -> RateLimitResult:
        """
        Checks if client/principal identifier is within rate limits for the given category.
        Returns:
            RateLimitResult(allowed: bool, remaining: int, retry_after: float, limit: int)
        """
        max_requests = self._get_category_limit(category, limit, is_local=is_local)
        now = time.time()
        cutoff = now - self.window_seconds
        key = f"{identifier}:{category.lower()}"

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
                return RateLimitResult(False, 0, retry_after, limit=max_requests)

            q.append(now)
            self._last_active[key] = now
            remaining = max(0, max_requests - len(q))
            return RateLimitResult(True, remaining, 0.0, limit=max_requests)

    def reset(self):
        with self._lock:
            self._requests.clear()
            self._last_active.clear()


# Global default rate limiter instance
global_rate_limiter = SlidingWindowRateLimiter(default_limit=60, window_seconds=60.0)


def check_category_rate_limit(
    request: Any,
    category: str,
    response: Any = None
) -> tuple[bool, dict[str, str], Any]:
    """
    Evaluates rate limit for the incoming request within a specific category.
    Returns:
        (allowed: bool, headers: dict[str, str], error_response: JSONResponse | None)
    """
    from fastapi.responses import JSONResponse

    client_ip = request.client.host if (request and getattr(request, "client", None)) else "127.0.0.1"
    is_local = client_ip in ("127.0.0.1", "::1", "localhost", "testclient", "testserver")

    res = global_rate_limiter.check_rate_limit(client_ip, category=category, is_local=is_local)
    headers = {
        "X-RateLimit-Limit": str(res.limit),
        "X-RateLimit-Remaining": str(res.remaining),
    }

    if not res.allowed:
        headers["Retry-After"] = str(int(res.retry_after))
        err_resp = JSONResponse(
            status_code=429,
            content={"error": f"Rate limit exceeded for category '{category}'. Please wait before making more requests."},
            headers=headers
        )
        return False, headers, err_resp

    if response is not None:
        for k, v in headers.items():
            response.headers[k] = v

    return True, headers, None

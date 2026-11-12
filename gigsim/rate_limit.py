"""Per-freelancer sliding-window rate limiting (60 requests/minute by default)."""

import time
from collections import defaultdict, deque

EXEMPT_PATHS = {"/health", "/", "/docs", "/openapi.json", "/redoc"}


class SlidingWindowLimiter:
    def __init__(self, limit_per_minute: int) -> None:
        self.limit = limit_per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """Record a hit; return (allowed, retry_after_seconds)."""
        now = time.monotonic() if now is None else now
        window = self._hits[key]
        while window and now - window[0] >= 60.0:
            window.popleft()
        if len(window) >= self.limit:
            retry_after = 60.0 - (now - window[0])
            return False, max(1, int(retry_after) + 1)
        window.append(now)
        return True, 0


def bearer_token_from_request(request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None

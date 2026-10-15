"""Small in-memory rate limiter for the public assistant endpoint (single-process demo)."""
import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from .services.errors import RateLimitedError


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > 10_000:  # crude cap so the table cannot grow without bound
                self._hits.clear()
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


def speech_rate_limit(request: Request) -> None:
    key = request.client.host if request.client else "unknown"
    if not request.app.state.speech_limiter.allow(key):
        raise RateLimitedError()


def assistant_rate_limit(request: Request) -> None:
    key = request.client.host if request.client else "unknown"
    if not request.app.state.assistant_limiter.allow(key):
        raise RateLimitedError()

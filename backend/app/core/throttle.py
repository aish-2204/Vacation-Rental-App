from collections import deque
from collections.abc import Callable
from math import ceil
from threading import Lock
from time import monotonic

from fastapi import Request

from app.core.errors import APIError


class LoginRateLimiter:
    """Bounded, per-process sliding window keyed by the actual connection IP.

    All attempts count, including successful logins. Forwarded IP headers are
    deliberately ignored. Deployment needs a shared/edge limit across replicas.
    """

    def __init__(
        self, max_attempts: int, window_seconds: int, *, clock: Callable[[], float] = monotonic
    ) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._clock = clock
        self._attempts: dict[str, deque[float]] = {}
        self._lock = Lock()

    def check(self, client_ip: str) -> None:
        with self._lock:
            now = self._clock()
            cutoff = now - self.window_seconds
            for key in list(self._attempts):
                attempts = self._attempts[key]
                while attempts and attempts[0] <= cutoff:
                    attempts.popleft()
                if not attempts:
                    del self._attempts[key]
            if client_ip not in self._attempts and len(self._attempts) >= 10000:
                self._reject(self.window_seconds)
            attempts = self._attempts.setdefault(client_ip, deque())
            if len(attempts) >= self.max_attempts:
                self._reject(max(1, ceil(attempts[0] + self.window_seconds - now)))
            attempts.append(now)

    @staticmethod
    def _reject(retry_after: int) -> None:
        raise APIError(
            429,
            "RATE_LIMITED",
            "Too many login attempts; try again later",
            headers={"Retry-After": str(retry_after)},
        )


def enforce_login_throttle(request: Request) -> None:
    # Uvicorn is configured to distrust proxy headers in the local Make target.
    # Any later reverse-proxy deployment must configure trusted proxies explicitly.
    client_ip = request.client.host if request.client else "unknown"
    request.app.state.login_limiter.check(client_ip)

"""Per-IP sliding-window rate limiting for the public /api/ endpoints.

In-memory and per-process by design: no external dependency, no shared store.
With N gunicorn workers the effective ceiling is N x API_RATE_LIMIT — acceptable
for abuse protection, not billing-grade metering.
"""
import threading
import time
from collections import defaultdict

from django.conf import settings
from django.http import JsonResponse

_lock = threading.Lock()
_hits: dict[str, list[float]] = defaultdict(list)
_last_prune = 0.0


def _client_ip(request) -> str:
    # Railway/most PaaS terminate TLS at a proxy; the client is the first
    # entry in X-Forwarded-For. Fall back to the direct socket address.
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


class ApiRateLimitMiddleware:
    PROTECTED_PREFIX = "/api/"

    def __init__(self, get_response):
        self.get_response = get_response
        self.limit = getattr(settings, "API_RATE_LIMIT", 30)
        self.window = getattr(settings, "API_RATE_WINDOW_SECONDS", 60)

    def __call__(self, request):
        if self.limit > 0 and request.path.startswith(self.PROTECTED_PREFIX):
            if not self._allow(_client_ip(request)):
                return JsonResponse(
                    {
                        "error": "Rate limit exceeded. Try again shortly.",
                        "limit": self.limit,
                        "window_seconds": self.window,
                    },
                    status=429,
                )
        return self.get_response(request)

    def _allow(self, ip: str) -> bool:
        global _last_prune
        now = time.time()
        with _lock:
            # Periodically drop idle IPs so the store can't grow unbounded.
            if now - _last_prune > self.window:
                stale = [k for k, v in _hits.items() if not v or now - v[-1] > self.window]
                for k in stale:
                    del _hits[k]
                _last_prune = now

            calls = [t for t in _hits[ip] if now - t < self.window]
            if len(calls) >= self.limit:
                _hits[ip] = calls
                return False
            calls.append(now)
            _hits[ip] = calls
            return True

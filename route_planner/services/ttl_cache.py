"""One shared in-process TTL cache for all external API responses.

Every external service (NWS, USDA, FMCSA, the LLM coach) should route through
this instead of re-implementing its own cache. In-process/per-worker by design:
no external dependency, and the data cached here (weather alerts, weekly reports,
DOT records, market-snapshot coaching) tolerates a per-worker copy. With N
gunicorn workers the effective cache is N independent copies — acceptable for
quota/latency reduction, and documented so nobody is surprised by it.
"""
import threading
import time

_lock = threading.Lock()
_store: dict = {}   # key -> (expires_at, value)


def get(key):
    """Return the cached value for key, or None if absent/expired."""
    now = time.time()
    with _lock:
        hit = _store.get(key)
        if hit and hit[0] > now:
            return hit[1]
        if hit:
            _store.pop(key, None)
    return None


def put(key, value, ttl_seconds: int):
    """Cache value under key for ttl_seconds. Never caches falsy values so a
    failed/empty fetch is retried rather than pinned."""
    if not value:
        return value
    with _lock:
        _store[key] = (time.time() + ttl_seconds, value)
        # Bound memory: prune expired entries when the store grows.
        if len(_store) > 500:
            now = time.time()
            for k, (exp, _) in list(_store.items()):
                if exp <= now:
                    _store.pop(k, None)
    return value


def cached_call(key, ttl_seconds: int, fn):
    """Return cached value for key, else call fn(), cache the result, return it."""
    hit = get(key)
    if hit is not None:
        return hit
    result = fn()
    return put(key, result, ttl_seconds) or result

"""Per-account brake on password guessing.

The old limit was 5 sign-ins a minute per IP address, which locked a whole office out when a few people
signed in together. This counts only FAILED attempts, per email address, so colleagues don't affect
each other and a guesser is stopped after a handful of wrong passwords.

Kept in memory: it resets when the server restarts, which is acceptable for a brake (the per-IP limit
and audit log still apply).
"""
import threading
import time
from collections import defaultdict, deque

MAX_FAILURES = 8      # wrong passwords allowed...
WINDOW_SECONDS = 300  # ...within this many seconds

_lock = threading.Lock()
_failures = defaultdict(deque)


def _key(email: str) -> str:
    return (email or "").strip().lower()[:254]


def _prune(q: deque, now: float) -> None:
    while q and now - q[0] > WINDOW_SECONDS:
        q.popleft()


def seconds_until_allowed(email: str) -> int:
    """0 if this account may try now, otherwise how long to wait."""
    now = time.monotonic()
    with _lock:
        q = _failures.get(_key(email))
        if not q:
            return 0
        _prune(q, now)
        if len(q) < MAX_FAILURES:
            return 0
        return max(1, int(WINDOW_SECONDS - (now - q[0])) + 1)


def record_failure(email: str) -> None:
    now = time.monotonic()
    with _lock:
        q = _failures[_key(email)]
        _prune(q, now)
        q.append(now)
        if len(_failures) > 10000:  # unknown emails can't grow this without limit
            for k in [k for k, v in _failures.items() if not v or now - v[-1] > WINDOW_SECONDS]:
                del _failures[k]


def record_success(email: str) -> None:
    with _lock:
        _failures.pop(_key(email), None)


def reset() -> None:
    with _lock:
        _failures.clear()

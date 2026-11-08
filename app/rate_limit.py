import threading
import time

MAX_FAILED_ATTEMPTS = 5
WINDOW_SECONDS = 15 * 60

_lock = threading.Lock()
_failures = {}  # key -> list of timestamps of failed logins


def _key(ip, email):
    return f"{ip}|{(email or '').strip().lower()}"


def _recent(key, now):
    stamps = [t for t in _failures.get(key, []) if now - t < WINDOW_SECONDS]
    if stamps:
        _failures[key] = stamps
    else:
        _failures.pop(key, None)
    return stamps


def seconds_until_allowed(ip, email):
    """0 if the login may be tried, otherwise how many seconds to wait."""
    now = time.time()
    with _lock:
        stamps = _recent(_key(ip, email), now)
        if len(stamps) >= MAX_FAILED_ATTEMPTS:
            return int(WINDOW_SECONDS - (now - stamps[0])) + 1
    return 0


def record_failure(ip, email):
    now = time.time()
    with _lock:
        key = _key(ip, email)
        _recent(key, now)
        _failures.setdefault(key, []).append(now)


def clear_failures(ip, email):
    with _lock:
        _failures.pop(_key(ip, email), None)
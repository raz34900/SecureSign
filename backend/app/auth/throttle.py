"""Failed-login throttling, keyed on the account being attempted.

Keyed on the account because the API cannot see the caller: behind Docker every request
arrives from nginx, so a per-address limit here would count the internet as one client.
Per-address limiting belongs in nginx. The key is whatever was submitted, resolved or
not - throttling only real accounts would answer 429 for names that exist and 401 for
names that do not, which is an existence oracle.
"""
import time

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 15 * 60

# Bounded, because an unauthenticated endpoint must not let a caller grow it. Full means
# full: evicting the oldest entry meant flooding junk usernames cleared a victim's
# lockout, since a locked account stops generating stamps and ages fastest.
MAX_TRACKED = 4096

_failures: dict[tuple[str, str], list[float]] = {}


def _purge(now: float) -> None:
    for key, stamps in list(_failures.items()):
        fresh = [stamp for stamp in stamps if now - stamp < WINDOW_SECONDS]
        if fresh:
            _failures[key] = fresh
        else:
            del _failures[key]


def retry_after(org_code: str, username: str) -> int:
    """Seconds until this account may try again, or 0 if it may try now."""
    now = time.time()
    _purge(now)
    stamps = _failures.get((org_code, username))
    if stamps is None:
        # Saturated and unknown: fail closed. Someone is flooding, and letting the flood
        # through unthrottled is worse than making them wait out the window.
        return WINDOW_SECONDS if len(_failures) >= MAX_TRACKED else 0
    if len(stamps) < MAX_ATTEMPTS:
        return 0
    return max(1, int(WINDOW_SECONDS - (now - stamps[-MAX_ATTEMPTS])))


def record_failure(org_code: str, username: str) -> None:
    now = time.time()
    _purge(now)
    if len(_failures) >= MAX_TRACKED and (org_code, username) not in _failures:
        return  # retry_after already refuses unknown keys while the store is full
    _failures.setdefault((org_code, username), []).append(now)


def clear(org_code: str, username: str) -> None:
    """A correct password ends the run. Someone who knows it is not the attacker."""
    _failures.pop((org_code, username), None)


def reset() -> None:
    _failures.clear()

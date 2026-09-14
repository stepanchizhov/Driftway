"""
Inbound limits for the expensive endpoint.

Generating a set of loops costs many routing calls — the figure recorded in
earlier notes is around fifteen per generation, which is historical rather than
a fresh measurement — so `/api/generate` is the one place where an anonymous
stranger can spend real money. The limiter here is about protecting that
budget, not about admission: a signed-out parent is entitled to plan drives,
just not to run a thousand of them a minute.

Three deliberate choices.

**Keyed by account or address, never by a client-chosen id.** The per-device id
is something the caller makes up, so keying on it would be a limiter anyone can
reset by editing a string. A signed-in caller is keyed by account so that a
household behind one address is not throttled by a neighbour.

**A global ceiling as well as a per-caller one.** Per-caller limits bound one
abuser; they do nothing about many callers at once, which is the shape of the
day the link gets posted somewhere busy. The global ceiling is the one that
actually protects the provider bill.

**In-process, with no new dependency.** Honest consequences: counters live in
this worker's memory, so they reset when the service restarts and are not
shared between instances. On a single-instance deployment that is the whole
truth; on a multi-instance one the effective limit is the configured number
times the instance count. A shared store is the upgrade path when that stops
being good enough, and it needs infrastructure that does not exist yet.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional

from fastapi import Request


def _int_env(name: str, default: int) -> int:
    try:
        value = int((os.getenv(name) or "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


def per_minute() -> int:
    return _int_env("GENERATE_PER_MINUTE", 6)


def per_hour() -> int:
    return _int_env("GENERATE_PER_HOUR", 40)


def global_per_hour() -> int:
    """Ceiling across everybody. The provider-budget backstop."""
    return _int_env("GENERATE_GLOBAL_PER_HOUR", 600)


def trusted_proxy_count() -> int:
    """How many proxies in front of us may be believed.

    Zero by default, and zero means X-Forwarded-For is ignored entirely.
    That is the safe default because the header is caller-supplied: trusting it
    without a proxy in front lets anyone mint a fresh limit bucket per request
    by changing one line. Render puts exactly one proxy in front, so set
    TRUSTED_PROXY_COUNT=1 there - see docs/DEPLOY.md.
    """
    try:
        return max(0, int((os.getenv("TRUSTED_PROXY_COUNT") or "0").strip()))
    except ValueError:
        return 0


def client_address(request: Request) -> str:
    """The caller's address, as far as it can be believed."""
    hops = trusted_proxy_count()
    if hops:
        forwarded = request.headers.get("x-forwarded-for") or ""
        chain = [part.strip() for part in forwarded.split(",") if part.strip()]
        if chain:
            # Count in from the right: the rightmost entries were appended by
            # infrastructure we control, anything further left was supplied by
            # the caller and cannot be trusted.
            index = max(0, len(chain) - hops)
            return chain[index]
    return (request.client.host if request.client else "") or "unknown"


class RateLimited(RuntimeError):
    """Too many requests. Carries how long to wait."""

    def __init__(self, retry_after: int, scope: str):
        self.retry_after = max(1, int(retry_after))
        self.scope = scope
        super().__init__("Too many route requests.")


@dataclass
class _Window:
    seconds: int
    limit: int


class SlidingWindowLimiter:
    """Request timestamps per key, trimmed to the longest window.

    Sliding rather than fixed: a fixed window lets a caller fire the whole
    allowance in the last second of one window and again in the first second of
    the next, which is exactly the burst this is meant to stop.
    """

    def __init__(self):
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, windows: list[_Window], *, scope: str) -> None:
        longest = max(w.seconds for w in windows)
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > longest:
                hits.popleft()

            for window in windows:
                cutoff = now - window.seconds
                used = sum(1 for t in hits if t > cutoff)
                if used >= window.limit:
                    oldest = next(t for t in hits if t > cutoff)
                    raise RateLimited(window.seconds - (now - oldest), scope)

            hits.append(now)
            self._sweep(now)

    def _sweep(self, now: float) -> None:
        """Drop keys that have gone quiet, so memory does not grow forever."""
        if len(self._hits) < 2048:
            return
        stale = [k for k, v in self._hits.items() if not v or now - v[-1] > 3600]
        for key in stale:
            self._hits.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_caller = SlidingWindowLimiter()
_global = SlidingWindowLimiter()

GLOBAL_KEY = "*"


def check_generate(request: Request, account_id: Optional[str] = None) -> None:
    """Raise RateLimited if this generation should not proceed.

    The global ceiling is checked first: when the service as a whole is at its
    budget, one caller's remaining personal allowance is irrelevant.
    """
    _global.check(
        GLOBAL_KEY, [_Window(3600, global_per_hour())], scope="service"
    )
    key = f"account:{account_id}" if account_id else f"addr:{client_address(request)}"
    _caller.check(
        key,
        [_Window(60, per_minute()), _Window(3600, per_hour())],
        scope="caller",
    )


def reset_all() -> None:
    """Test helper. Counters are per-process, so tests must clear them."""
    _caller.reset()
    _global.reset()

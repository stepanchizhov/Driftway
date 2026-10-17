"""
Provider calls, counted, and Driftway's own daily ceilings for TomTom's APIs
(founder and Astra brief, 15 Oct 2026: make provider usage understandable
before Google Play).

Every outside call is counted under its API ("tomtom.routing",
"tomtom.search", "tomtom.incidents", "tomtom.matrix", "ors.directions",
"ors.matrix", "ors.geocode", "overpass") and the operation it served
("drive", "walk", "own_route", "search", "meetup", "walk_area",
"monitoring", "other": set per request from its path, see middleware below).
Each API is its own pool: TomTom's free allowances are per API, and adding
them up would be a fiction.

TomTom's APIs get a daily ceiling of Driftway's own (TOMTOM_ROUTING_PER_DAY
and so on; HYPOTHESIS defaults, from the public pricing page's 20,000 free
Routing requests a month, not from the founder's account). At the ceiling a
call isn't made: drives and search fall back to openrouteservice as when
TomTom refuses, the walk stand-in says it can't help, roadworks say they
couldn't be checked. openrouteservice keeps its own budgets (core/ors.py).

Counts and ceilings live in this process: they start again on every deploy
or restart, and assume one server instance (as on Render today). The
founder's view: GET /api/admin/provider-usage.
"""

from __future__ import annotations

import os
from collections import Counter, deque
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Deque, Dict, Iterator, Optional

from .ratelimit import RateLimited, SlidingWindowLimiter, _Window

#: Daily ceilings per TomTom API, overridable by environment variable.
CEILING_ENV = {
    "tomtom.routing": ("TOMTOM_ROUTING_PER_DAY", 600),
    "tomtom.search": ("TOMTOM_SEARCH_PER_DAY", 600),
    "tomtom.incidents": ("TOMTOM_INCIDENTS_PER_DAY", 300),
    "tomtom.matrix": ("TOMTOM_MATRIX_PER_DAY", 100),
}

_counts: Counter = Counter()               # (api, operation) -> calls made
_refused: Counter = Counter()              # api -> calls not made at the ceiling
_since = datetime.now(timezone.utc)
_limiter = SlidingWindowLimiter()
_operation: ContextVar[str] = ContextVar("provider_operation", default="other")
_tally: ContextVar[Optional[Counter]] = ContextVar("provider_tally", default=None)
#: Calls per recent drive request, per API: the realistic range.
_drives: Deque[Dict[str, int]] = deque(maxlen=100)


def ceiling(api: str) -> Optional[int]:
    env = CEILING_ENV.get(api)
    if env is None:
        return None
    try:
        return max(0, int(os.getenv(env[0]) or env[1]))
    except ValueError:
        return env[1]


def spend(api: str) -> bool:
    """Count one call to `api`; False, without counting it as made, when
    Driftway's own daily ceiling for it is reached."""
    most = ceiling(api)
    if most == 0:                       # switched off: never called
        _refused[api] += 1
        return False
    if most is not None:
        try:
            _limiter.check(api, [_Window(86400, most)], scope="service")
        except RateLimited:
            _refused[api] += 1
            return False
    record(api)
    return True


def record(api: str) -> None:
    """Count a call made (for APIs with no ceiling of ours)."""
    _counts[(api, _operation.get())] += 1
    tally = _tally.get()
    if tally is not None:
        tally[api] += 1


@contextmanager
def operation(name: str) -> Iterator[Counter]:
    token, tally_token = _operation.set(name), _tally.set(Counter())
    tally = _tally.get()
    try:
        yield tally
    finally:
        if name == "drive" and tally:
            _drives.append(dict(tally))
        _operation.reset(token)
        _tally.reset(tally_token)


#: Which operation a request path serves.
PATHS = [("/api/generate", "drive"), ("/api/walks/generate", "walk"), ("/api/walks/trace", "own_route"),
         ("/api/walks/areas", "walk_area"), ("/api/search", "search"), ("/api/meetups", "meetup"),
         ("/api/health/providers", "monitoring")]


class UsageMiddleware:
    """Labels each request's provider calls with its operation (plain ASGI,
    so the label reaches every task the request starts)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        name = next((op for prefix, op in PATHS if path.startswith(prefix)), "other")
        with operation(name):
            return await self.app(scope, receive, send)


def current() -> Counter:
    """This request's calls so far (the middleware's tally), or an empty one."""
    return _tally.get() or Counter()


def summary() -> Dict:
    by_api: Counter = Counter()
    by_op: Dict[str, Dict[str, int]] = {}
    for (api, op), n in _counts.items():
        by_api[api] += n
        by_op.setdefault(op, {})[api] = by_op.get(op, {}).get(api, 0) + n
    drives = list(_drives)
    per_drive = {}
    for api in sorted({a for d in drives for a in d}):
        vals = sorted(d.get(api, 0) for d in drives)
        per_drive[api] = {"min": vals[0], "median": vals[len(vals) // 2], "max": vals[-1]}
    return {
        "since": _since.isoformat(timespec="seconds"),
        "note": "In this server process only: starts again on every deploy or restart.",
        "calls_by_api": dict(by_api),
        "calls_by_operation": by_op,
        "not_made_at_ceiling": dict(_refused),
        "ceilings_per_day": {api: ceiling(api) for api in CEILING_ENV},
        "per_drive_request": {"requests": len(drives), **per_drive},
    }


def reset() -> None:
    """For tests."""
    global _limiter
    _counts.clear()
    _refused.clear()
    _drives.clear()
    _limiter = SlidingWindowLimiter()

"""
openrouteservice, shared by everything that uses it.

Walks are made with it, and since 10 Oct 2026 it is also the stand-in when
TomTom cannot answer: driving routes, the Meet Halfway matrix and place
search. One key, one set of quotas (Standard plan, read from the dashboard
and the API's own x-ratelimit headers that day):

    directions  2000 a day, 40 a minute
    matrix       500 a day, 40 a minute
    geocoding   3000 a day, 100 a minute

so the budget is counted here, per endpoint, across every caller - a busy
afternoon of driving fallbacks must not leave nothing for walks, and the
reverse.

The count is per server process. Since 11 Oct 2026 a second server (Next,
docs/CHANNELS.md) uses the same key, so each server takes a share of the
budget: ORS_BUDGET_SHARE, a fraction from 0 to 1, default 1. The two shares
must add up to at most 1 (stable 1 and Next 0.1 leave room under the plan).

The host moved once without Driftway noticing (api.openrouteservice.org to
api.heigit.org, see docs/DEPLOY.md). The addresses are settings:

    ORS_BASE_URL          the routing API root, default
                          https://api.heigit.org/openrouteservice
                          (paths /v2/directions/..., /v2/matrix/...)
    ORS_FALLBACK_BASE_URL optional: a second openrouteservice routing API,
                          e.g. a self-hosted one (http://host:8080/ors); tried
                          when the first refuses or fails
    ORS_FALLBACK_API_KEY  its key, if it needs one
    PELIAS_BASE_URL       place search, default https://api.heigit.org/pelias/v1.
                          A self-hosted openrouteservice has no place search,
                          so this has no fallback.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Tuple

import httpx

log = logging.getLogger("driftway")

BASE_DEFAULT = "https://api.heigit.org/openrouteservice"
PELIAS_DEFAULT = "https://api.heigit.org/pelias/v1"

#: (window seconds, most calls) per endpoint: just under the plan's limits.
WINDOWS: Dict[str, Tuple[Tuple[int, int], ...]] = {
    "directions": ((60, 35), (86400, 1800)),
    "matrix": ((60, 35), (86400, 450)),
    "geocode": ((60, 90), (86400, 2700)),
}

_budgets: Dict[str, object] = {}


def budget_share() -> float:
    """This server's share of the plan, from ORS_BUDGET_SHARE (default 1).
    Unreadable or out of range: 1, the behaviour before the setting existed."""
    raw = (os.getenv("ORS_BUDGET_SHARE") or "").strip()
    try:
        share = float(raw) if raw else 1.0
    except ValueError:
        log.error("ORS_BUDGET_SHARE=%r is not a number; using 1", raw)
        return 1.0
    if not 0 < share <= 1:
        log.error("ORS_BUDGET_SHARE=%r is not between 0 and 1; using 1", raw)
        return 1.0
    return share


def windows(endpoint: str) -> List[Tuple[int, int]]:
    """The windows for `endpoint`, scaled to this server's share; at least
    one call per window, so a small share slows walks rather than ending them."""
    share = budget_share()
    return [(seconds, max(1, int(most * share))) for seconds, most in WINDOWS[endpoint]]


class OrsBudgetSpent(RuntimeError):
    """Driftway's own ceiling for this endpoint is reached."""


def api_key() -> str:
    return (os.getenv("ORS_API_KEY") or "").strip()


def configured() -> bool:
    return bool(api_key())


def base_url() -> str:
    return (os.getenv("ORS_BASE_URL") or BASE_DEFAULT).strip().rstrip("/")


def pelias_url() -> str:
    return (os.getenv("PELIAS_BASE_URL") or PELIAS_DEFAULT).strip().rstrip("/")


def fallback() -> Optional[Tuple[str, str]]:
    """(base, key) of the second openrouteservice, if one is set."""
    base = (os.getenv("ORS_FALLBACK_BASE_URL") or "").strip().rstrip("/")
    if not base:
        return None
    return base, (os.getenv("ORS_FALLBACK_API_KEY") or "").strip()


def spend(endpoint: str) -> None:
    """Count one call to `endpoint`, or refuse it if the budget is spent."""
    from core.ratelimit import RateLimited, SlidingWindowLimiter, _Window
    limiter = _budgets.get(endpoint)
    if limiter is None:
        limiter = _budgets[endpoint] = SlidingWindowLimiter()
    try:
        limiter.check("*", [_Window(a, b) for a, b in windows(endpoint)], scope="service")
    except RateLimited:
        raise OrsBudgetSpent(endpoint)


def reset_budgets() -> None:
    """For tests: every budget starts empty."""
    _budgets.clear()


def _failed(resp: Optional[httpx.Response]) -> bool:
    """Worth trying the other address: refused, throttled, or broken.
    A 400 or 404 is an answer about the request, and is not retried."""
    return resp is None or resp.status_code in (401, 403, 429) or resp.status_code >= 500


async def request(client: httpx.AsyncClient, method: str, path: str,
                  endpoint: str, count: bool = True, **kw) -> httpx.Response:
    """One call to openrouteservice: `path` under the routing API root, or
    under the place-search root for endpoint "geocode". Routing falls back to
    the second address when the first refuses or fails. Raises OrsBudgetSpent
    before any call if Driftway's own budget is spent, and httpx.HTTPError
    only if every address failed in transport."""
    if count:              # a caller that has already counted says count=False
        spend(endpoint)
    if endpoint == "geocode":
        targets: List[Tuple[str, str]] = [(pelias_url(), api_key())]
    else:
        targets = [(base_url(), api_key())]
        if fallback():
            targets.append(fallback())
    extra_headers = dict(kw.pop("headers", {}) or {})
    last_exc: Optional[Exception] = None
    resp: Optional[httpx.Response] = None
    from core import usage
    for i, (base, key) in enumerate(targets):
        usage.record(f"ors.{endpoint}")
        headers = dict(extra_headers)
        if key:
            headers["Authorization"] = key
        try:
            resp = await client.request(method, base + path, headers=headers, **kw)
            last_exc = None
        except httpx.HTTPError as e:
            last_exc, resp = e, None
            log.warning("openrouteservice transport error at address %d: %s",
                        i + 1, type(e).__name__)
        if not _failed(resp):
            return resp
        if i + 1 < len(targets):
            log.warning("openrouteservice address %d answered %s; trying the fallback",
                        i + 1, resp.status_code if resp is not None else "nothing")
    if resp is not None:
        return resp
    raise last_exc  # type: ignore[misc]

"""
Is each outside service still answering? One small real call to each.

Why this exists: on 10 Oct 2026 openrouteservice had moved its API and the
old address refused every request, and nobody noticed until a walk failed on
the founder's phone - the move had been announced on the provider's forum for
months. A daily check, run by the GitHub Actions schedule, turns that into a
failed run and an email the morning it starts.

Each check costs one provider call. Results are kept for CACHE_S, so this
public endpoint can make at most a handful of checks a day however often it is
called. Nothing personal is sent: the probes use fixed public places.

A provider that sends a Deprecation or Sunset header (RFC 9745, RFC 8594) is
reported with it - the warning a moved API may give before it goes.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Dict, Optional

import httpx

#: How long a result stands before the next real check.
CACHE_S = 6 * 3600

#: Fixed public places: Windsor town centre, and Datchet.
_A = (51.4816, -0.6105)
_B = (51.4836, -0.5793)
UA = "Driftway-provider-check/1.0 (+https://github.com/stepanchizhov/Driftway)"

_cache: Dict = {"at": 0.0, "result": None}


def _warning(resp: httpx.Response) -> Optional[str]:
    parts = [f"{h}: {resp.headers[h]}" for h in ("Deprecation", "Sunset") if h in resp.headers]
    return "; ".join(parts) or None


def _outcome(resp: Optional[httpx.Response], ok: bool, started: float,
             detail: str = "") -> Dict:
    out = {"ok": ok, "status": resp.status_code if resp is not None else None,
           "ms": round((time.monotonic() - started) * 1000)}
    if detail:
        out["detail"] = detail
    if resp is not None and _warning(resp):
        out["warning"] = _warning(resp)
    return out


async def _probe(name: str, call) -> Dict:
    started = time.monotonic()
    try:
        resp, ok, detail = await call()
        return _outcome(resp, ok, started, detail)
    except Exception as e:  # noqa: BLE001 - a check must never break the endpoint
        return _outcome(None, False, started, f"error: {type(e).__name__}")


async def run_checks(client: Optional[httpx.AsyncClient] = None) -> Dict:
    from core import ors
    own = client is None
    client = client or httpx.AsyncClient(timeout=20.0, headers={"User-Agent": UA})
    tomtom_key = (os.getenv("TOMTOM_API_KEY") or "").strip()
    checks = {}

    async def tomtom_routing():
        r = await client.get(
            f"https://api.tomtom.com/routing/1/calculateRoute/"
            f"{_A[0]},{_A[1]}:{_B[0]},{_B[1]}/json", params={"key": tomtom_key})
        return r, r.status_code == 200 and bool(r.json().get("routes")), ""

    async def tomtom_search():
        r = await client.get("https://api.tomtom.com/search/2/search/SL4%201NJ.json",
                             params={"key": tomtom_key, "limit": 1, "countrySet": "GB"})
        return r, r.status_code == 200 and bool(r.json().get("results")), ""

    async def ors_directions():
        r = await ors.request(client, "POST", "/v2/directions/foot-walking/geojson",
                              "directions", json={"coordinates": [[_A[1], _A[0]], [_B[1], _B[0]]]})
        left = r.headers.get("x-ratelimit-remaining")
        return r, r.status_code == 200, f"{left} left today" if left else ""

    async def ors_geocode():
        r = await ors.request(client, "GET", "/autocomplete", "geocode",
                              params={"text": "SL4 1NJ", "size": 1})
        return r, r.status_code == 200 and bool(r.json().get("features")), ""

    async def ors_matrix():
        r = await ors.request(client, "POST", "/v2/matrix/driving-car", "matrix",
                              json={"locations": [[_A[1], _A[0]], [_B[1], _B[0]]],
                                    "sources": [0], "destinations": [1]})
        return r, r.status_code == 200, ""

    async def auth0():
        domain = (os.getenv("AUTH0_DOMAIN") or "").strip()
        r = await client.get(f"https://{domain}/.well-known/openid-configuration")
        return r, r.status_code == 200, ""

    async def osm_tiles():
        r = await client.get("https://tile.openstreetmap.org/0/0/0.png")
        return r, r.status_code == 200, ""

    plan = {"osm_tiles": osm_tiles}
    if tomtom_key:
        plan.update(tomtom_routing=tomtom_routing, tomtom_search=tomtom_search)
    if ors.configured():
        plan.update(ors_directions=ors_directions, ors_geocode=ors_geocode,
                    ors_matrix=ors_matrix)
    if (os.getenv("AUTH0_DOMAIN") or "").strip():
        plan["auth0"] = auth0
    try:
        names = list(plan)
        results = await asyncio.gather(*(_probe(n, plan[n]) for n in names))
        checks = dict(zip(names, results))
    finally:
        if own:
            await client.aclose()

    from core.router import tomtom_status
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ok": all(c["ok"] for c in checks.values()),
        "providers": checks,
        # Whether live traffic is currently replaced by the stand-in.
        "tomtom_stood_down": not tomtom_status()["available"],
    }


async def cached_checks() -> Dict:
    now = time.monotonic()
    if _cache["result"] is None or now - _cache["at"] >= CACHE_S:
        _cache["result"] = await run_checks()
        _cache["at"] = now
    return {**_cache["result"], "cached_for_s": CACHE_S}

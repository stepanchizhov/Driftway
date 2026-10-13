"""
Walks from TomTom's walking routes, while openrouteservice is struggling
(founder, 13 Oct 2026: "This happens too often. We need a proper fallback").

openrouteservice is Driftway's walk router: it makes round trips of a length,
reports surfaces and way types, and its wheelchair routing keeps a pram's
rules. On 13 Oct 2026 its walking routing timed out for hours while its
wheelchair routing still answered. TomTom, which already plans the drives,
also routes on foot, quickly, on the same key. What it lacks:

  * no surfaces, way types or heights: a walk from it says so, and is never
    offered for a pram (a pram's rules can't be kept without them: product
    rule, 10 Oct 2026, preferences and stand-ins never weaken access rules);
  * no round trip: loops are made the way drives are, from waypoints on a
    triangle round the start, then fitted to the length once.

What TomTom receives: the start and two points the loop passes, as precise
coordinates, with the walking travel mode. No name, account or label; the
walks are not stored. TomTom already receives drive starts on the same terms.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict, List, Optional, Tuple

import httpx

from core.geometry import SHAPES, build_candidate, rescale_anchors
from core.models import Coord

log = logging.getLogger("driftway")

URL = "https://api.tomtom.com/routing/1/calculateRoute/{locs}/json"
ATTRIBUTION = "Walking routes © TomTom"
#: A triangle round the start, with waypoints at r, walks about this many r
#: (two sides of r, the far side 1.64 r, and paths aren't straight).
LENGTH_PER_RADIUS = 4.4
#: Directions tried, degrees from north.
BEARINGS = (0, 120, 240)
#: A loop missing its length by more than this is asked for once more.
FIT_SHARE = 0.15
TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT)


def configured() -> bool:
    return bool((os.getenv("TOMTOM_API_KEY") or "").strip())


def _feature(route: dict) -> Dict:
    """A TomTom route as a GeoJSON-like feature, as openrouteservice gives
    them ([lng, lat], no heights, no extras), for the shared walk builder."""
    coords = [[p["longitude"], p["latitude"]] for leg in route.get("legs", []) for p in leg.get("points", [])]
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"summary": {"distance": route.get("summary", {}).get("lengthInMeters", 0)}}}


async def _route(client: httpx.AsyncClient, start: Coord, anchors: List[Coord]) -> Optional[Dict]:
    from core.router import tomtom_limiter
    pts = [start, *anchors, start]
    locs = ":".join(f"{p.lat:.6f},{p.lng:.6f}" for p in pts)
    resp = None
    for attempt in range(3):
        await tomtom_limiter().wait()       # shared with drives
        try:
            resp = await client.get(URL.format(locs=locs), params={
                "key": (os.getenv("TOMTOM_API_KEY") or "").strip(),
                "travelMode": "pedestrian", "routeType": "shortest",
                # The same loop rule as drives: no road walked twice if avoidable.
                "avoid": "alreadyUsedRoads",
            })
        except httpx.HTTPError as e:
            # The type only: the error's text includes the URL, and the URL the key.
            log.warning("TomTom walking request error: %s", type(e).__name__)
            return None
        if resp.status_code != 429:
            break
        await asyncio.sleep(0.5 * (attempt + 1))
    if resp is None or resp.status_code != 200:
        log.warning("TomTom walking %s", resp.status_code if resp is not None else "nothing")
        return None
    routes = resp.json().get("routes") or []
    return _feature(routes[0]) if routes else None


def _length(feature: Dict) -> float:
    return float(feature["properties"]["summary"]["distance"] or 0)


async def loops(start: Tuple[float, float], length_m: float,
                client: Optional[httpx.AsyncClient] = None) -> List[Dict]:
    """Up to three walking loops of about `length_m` from `start`, as
    features; empty if TomTom can't make them."""
    if not configured():
        return []
    own = client is None
    client = client or _client()
    origin = Coord(lat=start[0], lng=start[1])
    radius_km = length_m / 1000.0 / LENGTH_PER_RADIUS
    try:
        sets = [build_candidate(origin, b, radius_km, SHAPES[0]) for b in BEARINGS]
        found = list(await asyncio.gather(*(_route(client, origin, a) for a in sets)))
        # One more ask for each loop well off its length, scaled by the miss.
        again = [(i, rescale_anchors(origin, sets[i], max(0.5, min(1.6, length_m / _length(f)))))
                 for i, f in enumerate(found) if f and _length(f) and abs(_length(f) - length_m) / length_m > FIT_SHARE]
        if again:
            redo = await asyncio.gather(*(_route(client, origin, a) for _i, a in again))
            for (i, _a), f in zip(again, redo):
                if f and abs(_length(f) - length_m) < abs(_length(found[i]) - length_m):
                    found[i] = f
    finally:
        if own:
            await client.aclose()
    return [f for f in found if f and len(f["geometry"]["coordinates"]) >= 2]

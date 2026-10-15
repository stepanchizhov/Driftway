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

Walks via checkpoints and routes of the parent's own (14 Oct 2026) use it
too: start, checkpoints and back in one request, TomTom's "no road twice"
making the way back another way; or the parent's own points in order.

What TomTom receives: the start and the points the walk passes (two made-up
loop points, or the parent's checkpoints or own route), as precise
coordinates, with the walking travel mode. No name, account or label; the
walks are not stored. TomTom already receives drive starts on the same terms.
"""

from __future__ import annotations

import asyncio
import logging
import math
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
#: Variants of a walk via checkpoints lean this share of the distance to the
#: last checkpoint to either side.
SIDE_SHARE = 0.3
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


async def _route(client: httpx.AsyncClient, start: Coord, anchors: List[Coord],
                 finish: Optional[Coord] = None, once: bool = True) -> Optional[Dict]:
    """Start, anchors, finish (the start again if none). `once`: no road
    walked twice where avoidable."""
    from core.router import tomtom_limiter
    pts = [start, *anchors, finish or start]
    params = {"travelMode": "pedestrian", "routeType": "shortest"}
    if once:
        # The same loop rule as drives: no road walked twice if avoidable.
        params["avoid"] = "alreadyUsedRoads"
    locs = ":".join(f"{p.lat:.6f},{p.lng:.6f}" for p in pts)
    resp = None
    from core import usage
    for attempt in range(3):
        if not usage.spend("tomtom.routing"):   # Driftway's daily ceiling
            return None
        await tomtom_limiter().wait()       # shared with drives
        try:
            resp = await client.get(URL.format(locs=locs), params={
                "key": (os.getenv("TOMTOM_API_KEY") or "").strip(), **params})
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


def _side_point(a: Tuple[float, float], b: Tuple[float, float], share: float) -> Tuple[float, float]:
    """A point beside the middle of a to b, `share` of their distance away
    (positive: to the left going from a to b)."""
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    k = math.cos(math.radians(mid[0]))
    dx, dy = (b[1] - a[1]) * k, b[0] - a[0]
    return (mid[0] + dx * share, mid[1] - dy * share / k)


async def via_loops(start: Tuple[float, float], pins: List[Tuple[float, float]],
                    client: Optional[httpx.AsyncClient] = None) -> List[Dict]:
    """Up to three walks from the start through the checkpoints in order and
    back another way: the direct one, and one leaning to each side of the
    line to the last checkpoint."""
    if not configured() or not pins:
        return []
    own = client is None
    client = client or _client()
    origin = Coord(lat=start[0], lng=start[1])
    as_coord = lambda p: Coord(lat=p[0], lng=p[1])  # noqa: E731
    sets = [[as_coord(p) for p in pins]]
    for share in (SIDE_SHARE, -SIDE_SHARE):
        sets.append([as_coord(_side_point(start, pins[-1], share))] + [as_coord(p) for p in pins])
    try:
        found = await asyncio.gather(*(_route(client, origin, a) for a in sets))
    finally:
        if own:
            await client.aclose()
    return [f for f in found if f and len(f["geometry"]["coordinates"]) >= 2]


async def through(points: List[Tuple[float, float]],
                  client: Optional[httpx.AsyncClient] = None) -> Optional[Dict]:
    """The parent's own route through `points`, in order (roads may be walked
    twice: it is their route)."""
    if not configured() or len(points) < 2:
        return None
    own = client is None
    client = client or _client()
    c = [Coord(lat=p[0], lng=p[1]) for p in points]
    try:
        return await _route(client, c[0], c[1:-1], finish=c[-1], once=False)
    finally:
        if own:
            await client.aclose()

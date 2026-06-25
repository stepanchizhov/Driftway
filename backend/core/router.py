"""
Routing adapter.

A provider-neutral interface so the rest of the app never imports TomTom
directly. Swap providers by changing ROUTING_PROVIDER in config; the scorer,
validator and endpoint are untouched.

Implementations:
  - MockRouter:   no API key needed. Estimates duration/distance from geometry
                  so the whole pipeline runs end-to-end on your laptop.
  - TomTomRouter: real traffic-aware routing via TomTom Calculate Route.

Both return the same EvaluatedRoute shape.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import random
from dataclasses import dataclass, field
from typing import List, Optional, Protocol

import httpx

log = logging.getLogger("driftway")

from .geometry import haversine_km
from .models import Coord, RoadMix


@dataclass
class EvaluatedRoute:
    anchors: List[Coord]            # the intermediate anchors we requested
    minutes: float                  # traffic-aware duration
    distance_km: float
    road_mix: RoadMix
    geometry: List[Coord] = field(default_factory=list)  # full path, if provided
    has_uturn: bool = False
    raw: Optional[dict] = None


class Router(Protocol):
    name: str
    async def evaluate(self, start: Coord, finish: Coord,
                       anchors: List[Coord], profile: str) -> Optional[EvaluatedRoute]:
        ...


# --------------------------------------------------------------------------
# Mock implementation
# --------------------------------------------------------------------------

# Rough average speeds the mock uses to turn distance into time. Deliberately
# a bit different from the geometry seed speeds so the rescale loop gets
# exercised during local testing.
_MOCK_SPEED = {"motorway": 80.0, "mixed": 46.0, "quiet": 32.0}
_MOCK_MIX = {
    "motorway": RoadMix(motorway=0.55, primary=0.30, secondary=0.10, residential=0.05),
    "mixed": RoadMix(motorway=0.15, primary=0.40, secondary=0.30, residential=0.15),
    "quiet": RoadMix(motorway=0.0, primary=0.15, secondary=0.45, residential=0.40),
}


class MockRouter:
    name = "mock"

    def __init__(self, seed: int = 0):
        self._rng = random.Random(seed)

    async def evaluate(self, start, finish, anchors, profile):
        # Sum the leg distances along start -> anchors... -> finish.
        pts = [start, *anchors, finish]
        road_dist = 0.0
        for i in range(len(pts) - 1):
            # multiply straight-line by a wiggle factor to mimic real roads
            road_dist += haversine_km(pts[i], pts[i + 1]) * 1.25
        speed = _MOCK_SPEED.get(profile, 46.0)
        # add +/-8% noise so candidates differ and rescaling has work to do
        noise = 1.0 + self._rng.uniform(-0.08, 0.08)
        minutes = (road_dist / speed) * 60.0 * noise
        return EvaluatedRoute(
            anchors=anchors,
            minutes=round(minutes, 1),
            distance_km=round(road_dist, 1),
            road_mix=_MOCK_MIX.get(profile, _MOCK_MIX["mixed"]),
            geometry=pts,
        )


# --------------------------------------------------------------------------
# TomTom implementation
# --------------------------------------------------------------------------

_TOMTOM_BASE = "https://api.tomtom.com/routing/1/calculateRoute"

# TomTom does not return a clean "road class mix", so for the alpha we infer a
# coarse mix from the route summary. HYPOTHESIS: replace with section analysis
# (Calculate Route supports sectionType=travelMode etc.) once we know which
# signal predicts "would use again".
_TOMTOM_TRAVEL_MODE = "car"


class _RateLimiter:
    """Caps how often requests *start*, to respect TomTom's QPS ceiling.

    The free tier allows 5 calls/second for non-tile APIs. We fire many route
    candidates per request, so without this they'd burst past the limit and get
    throttled (HTTP 429). This spaces request starts ~`1/rate` seconds apart.
    """

    def __init__(self, rate_per_sec: float):
        self._min_interval = 1.0 / rate_per_sec
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = asyncio.get_event_loop().time()
            if now < self._next:
                await asyncio.sleep(self._next - now)
                now = asyncio.get_event_loop().time()
            self._next = now + self._min_interval


# TomTom free tier: 5 req/sec. Stay just under it.
_TOMTOM_RATE = 4.0
_TOMTOM_MAX_RETRIES = 3


class TomTomRouter:
    name = "tomtom"

    def __init__(self, api_key: str, client: Optional[httpx.AsyncClient] = None):
        if not api_key:
            raise ValueError("TomTom API key is required for TomTomRouter")
        self._key = api_key
        self._client = client or httpx.AsyncClient(timeout=12.0)
        self._limiter = _RateLimiter(_TOMTOM_RATE)

    async def evaluate(self, start, finish, anchors, profile):
        # Build the "lat,lng:lat,lng:..." locations string.
        pts = [start, *anchors, finish]
        locs = ":".join(f"{p.lat:.6f},{p.lng:.6f}" for p in pts)
        url = f"{_TOMTOM_BASE}/{locs}/json"

        params = {
            "key": self._key,
            "traffic": "true",
            "travelMode": _TOMTOM_TRAVEL_MODE,
            "routeType": "fastest",
            "computeTravelTimeFor": "all",
        }
        # Nudge the engine toward / away from motorways by profile.
        if profile == "quiet":
            params["avoid"] = "motorways"
        elif profile == "motorway":
            params["routeType"] = "fastest"

        data = None
        for attempt in range(_TOMTOM_MAX_RETRIES):
            await self._limiter.wait()
            try:
                resp = await self._client.get(url, params=params)
            except httpx.HTTPError as e:
                log.warning("TomTom request error: %s", e)
                continue  # transient; retry

            if resp.status_code == 429:
                # Throttled. Back off a little and retry.
                wait_s = 0.5 * (attempt + 1)
                log.warning("TomTom 429 (throttled); backing off %.1fs", wait_s)
                await asyncio.sleep(wait_s)
                continue
            if resp.status_code in (401, 403):
                # Auth/permission problem — retrying won't help. Log loudly once.
                log.error(
                    "TomTom %s: key rejected or Routing product not enabled. "
                    "Body: %.200s",
                    resp.status_code,
                    resp.text,
                )
                return None
            if resp.status_code >= 400:
                log.warning("TomTom %s: %.200s", resp.status_code, resp.text)
                continue
            try:
                data = resp.json()
                break
            except ValueError:
                log.warning("TomTom returned non-JSON body")
                continue

        if data is None:
            return None  # all attempts failed; caller treats as "candidate failed"

        routes = data.get("routes") or []
        if not routes:
            return None
        summary = routes[0].get("summary", {})
        minutes = summary.get("travelTimeInSeconds", 0) / 60.0
        distance_km = summary.get("lengthInMeters", 0) / 1000.0

        geometry: List[Coord] = []
        for leg in routes[0].get("legs", []):
            for pt in leg.get("points", []):
                geometry.append(Coord(lat=pt["latitude"], lng=pt["longitude"]))

        return EvaluatedRoute(
            anchors=anchors,
            minutes=round(minutes, 1),
            distance_km=round(distance_km, 1),
            road_mix=_infer_mix(profile),   # coarse for alpha; see note above
            geometry=geometry,
            raw=summary,
        )


def _infer_mix(profile: str) -> RoadMix:
    return _MOCK_MIX.get(profile, _MOCK_MIX["mixed"])


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------

def get_router() -> Router:
    provider = os.getenv("ROUTING_PROVIDER", "mock").lower()
    if provider == "tomtom":
        return TomTomRouter(api_key=os.getenv("TOMTOM_API_KEY", ""))
    return MockRouter()

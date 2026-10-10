"""
Routing adapter.

A provider-neutral interface so the rest of the app never imports TomTom
directly. Swap providers by changing ROUTING_PROVIDER in config; the scorer,
validator and endpoint are untouched.

Implementations:
  - MockRouter:   no API key needed. Estimates duration/distance from geometry
                  so the whole pipeline runs end-to-end on your laptop.
  - TomTomRouter: real traffic-aware routing via TomTom Calculate Route.
  - ORSRouter:    openrouteservice driving routes and matrix - real roads, but
                  no live traffic. The stand-in when TomTom cannot answer.
  - FailoverRouter: TomTom first; openrouteservice while TomTom is failing.

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
    #: False when the time comes from a provider without live traffic; the
    #: route then says so rather than presenting a guess as a live estimate.
    live_traffic: bool = True


class Router(Protocol):
    name: str
    async def evaluate(self, start: Coord, finish: Coord,
                       anchors: List[Coord], profile: str) -> Optional[EvaluatedRoute]:
        ...

    async def travel_matrix(self, origins: List[Coord], destinations: List[Coord],
                            profile: str) -> List[List[Optional[float]]]:
        """Minutes from every origin to every destination.

        Meet Halfway needs participants x venues, which is a matrix question,
        not N route questions. Asking it as a matrix keeps a two-parent,
        five-venue plan at one provider call instead of ten.

        Returns a grid indexed [origin][destination]; a cell is None when that
        pair could not be routed.
        """
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


    async def travel_matrix(self, origins, destinations, profile):
        speed = _MOCK_SPEED.get(profile, 46.0)
        grid = []
        for o in origins:
            row = []
            for d in destinations:
                km = haversine_km(o, d) * 1.25
                row.append(round((km / speed) * 60.0, 1))
            grid.append(row)
        return grid


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

#: How long TomTom is treated as down after it refuses or fails, before it is
#: tried again. Module-level because a router is made per request, and the
#: whole point is that the next request does not wait on a dead provider.
TOMTOM_COOLDOWN_S = 300.0
_tomtom_down_until = 0.0
_tomtom_down_reason = ""


def _no_numbers(text: str) -> str:
    """A provider error body with every number blanked. TomTom's can repeat
    the request's coordinates ("no route between points (51.48, -0.61)"),
    which must not reach the logs (privacy policy, 10 Oct 2026)."""
    import re
    return re.sub(r"-?\d+(\.\d+)?", "#", text or "")[:200]


def tomtom_available() -> bool:
    import time
    return time.monotonic() >= _tomtom_down_until


def _tomtom_failed(reason: str) -> None:
    """TomTom refused (key, quota) or broke (5xx, network): stand it down."""
    global _tomtom_down_until, _tomtom_down_reason
    import time
    if tomtom_available():
        log.error("TomTom unavailable (%s); using the fallback for %.0f s",
                  reason, TOMTOM_COOLDOWN_S)
    _tomtom_down_until = time.monotonic() + TOMTOM_COOLDOWN_S
    _tomtom_down_reason = reason


def tomtom_status() -> dict:
    return {"available": tomtom_available(),
            "reason": None if tomtom_available() else _tomtom_down_reason}


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
            # Guidance rides along in the same request (no extra quota) and is
            # the only reliable way to know the driver would be asked to turn
            # around - which, with a sleeping baby aboard, is the whole point.
            "instructionsType": "coded",
            # Measured 10 Oct 2026 on 33 generated 30-minute loops per variant
            # from four Windsor-area starts: loops with no turn-around went
            # from 0 to 5 of 11 picks, loops repeating >=10% of their road
            # from 6 to 0, with the same time accuracy, at about three more
            # calls per request. routeType=thrilling (low windingness and
            # hilliness) was measured too and added signals without fewer
            # turn-arounds, so it is not used. See docs/DRIVING.md.
            "avoid": ["alreadyUsedRoads"],
        }
        # Nudge the engine toward / away from motorways by profile.
        if profile == "quiet":
            params["avoid"] = ["alreadyUsedRoads", "motorways"]
        elif profile == "motorway":
            params["routeType"] = "fastest"

        data = None
        failure = None          # why TomTom itself failed, if it did
        for attempt in range(_TOMTOM_MAX_RETRIES):
            await self._limiter.wait()
            try:
                resp = await self._client.get(url, params=params)
            except httpx.HTTPError as e:
                # The type only: an httpx error's text includes the URL, and
                # the URL carries the key.
                log.warning("TomTom request error: %s", type(e).__name__)
                failure = f"network: {type(e).__name__}"
                continue  # transient; retry

            if resp.status_code == 429:
                # Throttled. Back off a little and retry.
                wait_s = 0.5 * (attempt + 1)
                log.warning("TomTom 429 (throttled); backing off %.1fs", wait_s)
                failure = "throttled (429)"
                await asyncio.sleep(wait_s)
                continue
            if resp.status_code in (401, 403):
                # Auth/permission problem — retrying won't help. Log loudly once.
                log.error(
                    "TomTom %s: key rejected or Routing product not enabled. "
                    "Body: %.200s",
                    resp.status_code,
                    _no_numbers(resp.text),
                )
                _tomtom_failed(f"refused ({resp.status_code})")
                return None
            if resp.status_code >= 500:
                log.warning("TomTom %s: %.200s", resp.status_code, _no_numbers(resp.text))
                failure = f"server error ({resp.status_code})"
                continue
            if resp.status_code >= 400:
                # About this request (no route between these points), not
                # about TomTom: not a reason to stand it down.
                log.warning("TomTom %s: %.200s", resp.status_code, _no_numbers(resp.text))
                failure = None
                continue
            try:
                data = resp.json()
                break
            except ValueError:
                log.warning("TomTom returned non-JSON body")
                continue

        if data is None:
            if failure:
                _tomtom_failed(failure)
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
            has_uturn=_has_uturn(routes[0]),
            raw=summary,
        )


    async def travel_matrix(self, origins, destinations, profile):
        """TomTom Matrix Routing v2.

        Verified live: one POST returns every origin/destination pair with
        traffic-aware travel times. Falls back to None cells rather than
        raising, so one unroutable venue does not sink a whole meetup.
        """
        if not origins or not destinations:
            return []

        body = {
            "origins": [{"point": {"latitude": o.lat, "longitude": o.lng}}
                        for o in origins],
            "destinations": [{"point": {"latitude": d.lat, "longitude": d.lng}}
                             for d in destinations],
        }
        params = {"key": self._key, "routeType": "fastest", "traffic": "live"}
        if profile == "quiet":
            params["avoid"] = "motorways"

        grid: List[List[Optional[float]]] = [
            [None] * len(destinations) for _ in origins
        ]
        try:
            resp = await self._client.post(
                "https://api.tomtom.com/routing/matrix/2", params=params, json=body,
            )
        except httpx.HTTPError as e:
            log.warning("TomTom matrix transport error: %s", type(e).__name__)
            _tomtom_failed(f"network: {type(e).__name__}")
            return grid

        if resp.status_code >= 400:
            log.warning("TomTom matrix HTTP %s: %.160s", resp.status_code, _no_numbers(resp.text))
            if resp.status_code in (401, 403, 429) or resp.status_code >= 500:
                _tomtom_failed(f"matrix {resp.status_code}")
            return grid

        try:
            data = resp.json()
        except ValueError:
            log.warning("TomTom matrix returned non-JSON")
            return grid

        for cell in data.get("data", []):
            i = cell.get("originIndex")
            j = cell.get("destinationIndex")
            summary = cell.get("routeSummary") or {}
            secs = summary.get("travelTimeInSeconds")
            if i is None or j is None or secs is None:
                continue
            if 0 <= i < len(origins) and 0 <= j < len(destinations):
                grid[i][j] = round(secs / 60.0, 1)
        return grid


# --------------------------------------------------------------------------
# openrouteservice: the stand-in
# --------------------------------------------------------------------------

#: openrouteservice instruction type for a U-turn (documented list:
#: giscience.github.io/openrouteservice/api-reference/endpoints/directions/instruction-types).
_ORS_UTURN = 9
#: How far an anchor may be from a road. Anchors are generated points and can
#: land in a field; checked live 10 Oct 2026 with 1000 m.
_ORS_SNAP_M = 1000


class ORSRouter:
    """Driving routes and travel times from openrouteservice.

    Real roads and real geometry, but no live traffic: its times are typical
    ones. Every route it makes is marked live_traffic=False and says so on
    its card. Checked live 10 Oct 2026 on api.heigit.org: waypoints, "avoid
    motorways" (avoid_features: highways) and the matrix all answer with the
    key walks already use. It shares that key's quotas with walking - see
    core/ors.py.
    """

    name = "openrouteservice"

    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self._client = client or httpx.AsyncClient(timeout=20.0)

    async def evaluate(self, start, finish, anchors, profile):
        from core import ors
        pts = [start, *anchors, finish]
        body = {
            "coordinates": [[p.lng, p.lat] for p in pts],
            "radiuses": [_ORS_SNAP_M] * len(pts),
            "instructions": True,
        }
        if profile == "quiet":
            body["options"] = {"avoid_features": ["highways"]}
        try:
            resp = await ors.request(self._client, "POST",
                                     "/v2/directions/driving-car/geojson",
                                     "directions", json=body)
        except ors.OrsBudgetSpent:
            log.warning("openrouteservice driving budget spent")
            return None
        except httpx.HTTPError as e:
            log.warning("openrouteservice driving transport error: %s", type(e).__name__)
            return None
        if resp.status_code != 200:
            # The body can echo coordinates: status only.
            log.warning("openrouteservice driving %s", resp.status_code)
            return None
        feats = resp.json().get("features") or []
        if not feats:
            return None
        props = feats[0].get("properties", {})
        summary = props.get("summary", {})
        steps = [st for seg in props.get("segments", []) for st in seg.get("steps", [])]
        return EvaluatedRoute(
            anchors=anchors,
            minutes=round(summary.get("duration", 0) / 60.0, 1),
            distance_km=round(summary.get("distance", 0) / 1000.0, 1),
            road_mix=_infer_mix(profile),
            geometry=[Coord(lat=c[1], lng=c[0])
                      for c in feats[0]["geometry"]["coordinates"]],
            has_uturn=any(st.get("type") == _ORS_UTURN for st in steps),
            raw=summary,
            live_traffic=False,
        )

    async def travel_matrix(self, origins, destinations, profile):
        from core import ors
        grid: List[List[Optional[float]]] = [[None] * len(destinations) for _ in origins]
        if not origins or not destinations:
            return []
        body = {
            "locations": [[p.lng, p.lat] for p in [*origins, *destinations]],
            "sources": list(range(len(origins))),
            "destinations": list(range(len(origins), len(origins) + len(destinations))),
            "metrics": ["duration"],
        }
        try:
            resp = await ors.request(self._client, "POST", "/v2/matrix/driving-car",
                                     "matrix", json=body)
        except (ors.OrsBudgetSpent, httpx.HTTPError) as e:
            log.warning("openrouteservice matrix unavailable: %s", type(e).__name__)
            return grid
        if resp.status_code != 200:
            log.warning("openrouteservice matrix %s", resp.status_code)
            return grid
        for i, row in enumerate(resp.json().get("durations") or []):
            for j, secs in enumerate(row or []):
                if secs is not None and i < len(origins) and j < len(destinations):
                    grid[i][j] = round(secs / 60.0, 1)
        return grid


class FailoverRouter:
    """TomTom first; openrouteservice while TomTom is refusing or failing.

    A route TomTom simply cannot find is TomTom's answer, not a failure, and
    is not asked again elsewhere. When TomTom stands down (see
    _tomtom_failed) every call goes to the stand-in until the cooldown ends.
    """

    def __init__(self, primary, backup):
        self.primary = primary
        self.backup = backup

    @property
    def name(self) -> str:
        return self.primary.name if tomtom_available() else self.backup.name

    async def evaluate(self, start, finish, anchors, profile):
        if tomtom_available():
            route = await self.primary.evaluate(start, finish, anchors, profile)
            if route is not None or tomtom_available():
                return route
        return await self.backup.evaluate(start, finish, anchors, profile)

    async def travel_matrix(self, origins, destinations, profile):
        if tomtom_available():
            grid = await self.primary.travel_matrix(origins, destinations, profile)
            if tomtom_available():
                return grid
        return await self.backup.travel_matrix(origins, destinations, profile)


def _has_uturn(route: dict) -> bool:
    """True when the guidance asks the driver to turn around.

    TomTom spells these MAKE_UTURN / TRY_MAKE_UTURN depending on how confident
    it is that the manoeuvre is legal, so match on the stem rather than the
    exact codes.
    """
    instructions = (route.get("guidance") or {}).get("instructions") or []
    return any("UTURN" in (i.get("maneuver") or "") for i in instructions)


def _infer_mix(profile: str) -> RoadMix:
    return _MOCK_MIX.get(profile, _MOCK_MIX["mixed"])


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------

def get_router() -> Router:
    """TomTom, with openrouteservice standing in whenever TomTom fails - if an
    openrouteservice key is set. Without either key, simulated routing, so the
    alpha still runs end-to-end on a laptop."""
    from core import ors
    provider = os.getenv("ROUTING_PROVIDER", "mock").lower()
    if provider == "tomtom":
        key = os.getenv("TOMTOM_API_KEY", "").strip()
        if not key:
            if ors.configured():
                log.warning("TOMTOM_API_KEY is empty; routing with openrouteservice")
                return ORSRouter()
            # Misconfiguration should degrade, not 500 on every request.
            log.warning(
                "ROUTING_PROVIDER=tomtom but TOMTOM_API_KEY is empty; "
                "using simulated routing instead"
            )
            return MockRouter()
        primary = TomTomRouter(api_key=key)
        return FailoverRouter(primary, ORSRouter()) if ors.configured() else primary
    if provider == "openrouteservice" and ors.configured():
        return ORSRouter()
    return MockRouter()

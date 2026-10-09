"""
Walks generated from wherever the parent is, via openrouteservice.

Curated walks start at fixed public places, which founder testing showed is the
wrong shape for real use: a tester in Berlin had to walk eight minutes to the
start of her own regular route. This asks openrouteservice for round trips of
the right length from a chosen start, then judges them with exactly the same
pram and carrier rules as the curated walks.

What openrouteservice gives, and what it does not (documentation checked
9 Oct 2026, https://giscience.github.io/openrouteservice/api-reference/):

  * a round trip of a preferred length from one point (`round_trip`: length,
    points, seed - "a preferred value, but results may be different")
  * steps avoided on request
  * per-stretch surface and way type as [start point, end point, code] ranges
  * a height per point (SRTM, coarser than the 25 m model the curated walks use)
  * NOT gates, stiles or kerbs. Generated walks say so rather than implying
    there are none.

Terms (founder-reviewed, 9 Oct): results are CC-BY-SA 4.0 and need the
attribution below; personal data must not be sent. So requests go from this
server only, carry the start point and nothing that identifies anyone, are not
logged with that point, and generated walks are not stored.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date
from typing import Dict, List, Optional, Tuple

import httpx

from .catalogue import PACE_KMH, Route
from .evidence import Barrier, BarrierKind, Evidence, Section, Status, Surface
from .terrain import attach_gradients, smooth

log = logging.getLogger("driftway")

ORS_URL = "https://api.openrouteservice.org/v2/directions/{profile}/geojson"
ATTRIBUTION = "© openrouteservice by HeiGIT | Data from OpenStreetMap"
SOURCE = "openrouteservice (OpenStreetMap data)"
HEIGHT_SOURCE = "SRTM via openrouteservice"

#: Longest single section, as for curated walks: a long stretch would smear a
#: local slope over its whole length.
MAX_SECTION_M = 300.0

#: Seeds for alternative loops. Three variants per request: enough to choose
#: between, few enough to stay well inside the free plan.
SEEDS = (1, 2, 3)

# Surface IDs, https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/extra-info/surface
SURFACE = {
    0: (None, Surface.UNKNOWN), 1: ("paved", Surface.SEALED),
    2: ("unpaved", Surface.UNPAVED), 3: ("asphalt", Surface.SEALED),
    4: ("concrete", Surface.SEALED), 5: ("cobblestone", Surface.SETTS),
    6: ("metal", Surface.SEALED), 7: ("wood", Surface.SEALED),
    8: ("compacted gravel", Surface.COMPACTED), 9: ("fine gravel", Surface.COMPACTED),
    10: ("gravel", Surface.LOOSE), 11: ("dirt", Surface.SOFT),
    12: ("ground", Surface.SOFT), 13: ("ice", Surface.LOOSE),
    14: ("paving stones", Surface.SEALED), 15: ("sand", Surface.SOFT),
    16: ("woodchips", Surface.SOFT), 17: ("grass", Surface.SOFT),
    18: ("grass paver", Surface.SOFT),
}

# Way type IDs, https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/extra-info/waytype
WAYTYPE = {
    0: "Way", 1: "Main road", 2: "Road", 3: "Street", 4: "Path", 5: "Track",
    6: "Cycle path", 7: "Footpath", 8: "Steps", 9: "Ferry", 10: "Under construction",
}
STEPS = 8


class GenerationUnavailable(RuntimeError):
    """Generation cannot run - not configured, or the provider failed."""


def api_key() -> str:
    return (os.getenv("ORS_API_KEY") or "").strip()


def is_configured() -> bool:
    return bool(api_key())


def target_length_m(minutes: int) -> float:
    """The round-trip length to ask for. A preference, not a promise: the
    result is fitted to the time afterwards, like any other walk."""
    return minutes / 60.0 * PACE_KMH * 1000.0


def request_body(start: Tuple[float, float], profile: str, minutes: int,
                 seed: int) -> Tuple[str, Dict]:
    """The ORS profile and request body for one candidate loop."""
    ors_profile = "wheelchair" if profile == "pram" else "foot-walking"
    body = {
        # ORS takes [longitude, latitude].
        "coordinates": [[start[1], start[0]]],
        "options": {
            "round_trip": {"length": round(target_length_m(minutes)),
                           "points": 4, "seed": seed},
        },
        "elevation": True,
        "extra_info": ["surface", "waytype"],
        "instructions": False,
    }
    if profile == "pram":
        body["options"]["avoid_features"] = ["steps"]
    return ors_profile, body


def _haversine(a, b) -> float:
    import math
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


def route_from_ors(feature: Dict, *, walk_id: str, name: str,
                   start_label: str) -> Route:
    """Turn one ORS GeoJSON feature into a Route the catalogue can judge."""
    coords = feature["geometry"]["coordinates"]          # [lng, lat, ele]
    pts = [(c[1], c[0]) for c in coords]
    heights = [c[2] if len(c) > 2 else 0.0 for c in coords]
    dist = [0.0]
    for a, b in zip(pts, pts[1:]):
        dist.append(dist[-1] + _haversine(a, b))

    extras = feature.get("properties", {}).get("extras", {})

    def ranges(name: str) -> List[Tuple[int, int, int]]:
        return [tuple(v) for v in extras.get(name, {}).get("values", [])]

    surf_r, way_r = ranges("surface"), ranges("waytype")

    def value_at(rs, i, default=0):
        for a, b, v in rs:
            if a <= i < b:
                return v
        return default

    # Break points: wherever surface or way type changes, and every
    # MAX_SECTION_M so a slope stays where it is.
    cuts = sorted({0, len(pts) - 1, *[r[0] for r in surf_r + way_r]})
    bounds: List[int] = []
    for a, b in zip(cuts, cuts[1:]):
        bounds.append(a)
        mark = dist[a]
        for i in range(a + 1, b):
            if dist[i] - mark >= MAX_SECTION_M:
                bounds.append(i)
                mark = dist[i]
    bounds.append(len(pts) - 1)

    sections: List[Section] = []
    for a, b in zip(bounds, bounds[1:]):
        if b <= a:
            continue
        raw, cls = SURFACE.get(value_at(surf_r, a), (None, Surface.UNKNOWN))
        way = value_at(way_r, a)
        sec = Section(dist[a], dist[b], WAYTYPE.get(way, "Way"),
                      [[round(p[0], 6), round(p[1], 6)] for p in pts[a:b + 1]],
                      surface=cls)
        if raw:
            sec.evidence.append(Evidence("surface", raw, Status.MAPPED, SOURCE))
        if way == STEPS:
            sec.barriers.append(Barrier(BarrierKind.STEPS, (dist[a] + dist[b]) / 2,
                                        Status.MAPPED, SOURCE))
        sections.append(sec)

    attach_gradients(sections, dist, smooth(heights), HEIGHT_SOURCE)

    return Route(
        id=walk_id, name=name, area="", shape="loop",
        summary="Made from your start along mapped paths.",
        start={"lat": pts[0][0], "lng": pts[0][1], "label": start_label},
        sections=sections,
        sources=[{"id": "ors", "label": "openrouteservice",
                  "attribution": ATTRIBUTION, "licence": "CC-BY-SA 4.0"},
                 {"id": "osm", "label": "OpenStreetMap",
                  "attribution": "© OpenStreetMap contributors"}],
        built_on=date.today().isoformat(),
        notes=[
            "Generated just now from mapped paths; nobody has checked it on foot.",
            "Gates, stiles and kerbs are not reported for generated walks. "
            "There may be some.",
            "Heights come from a coarser model than the curated walks use, so "
            "short steep bits may not show.",
        ],
    )


async def generate(start: Tuple[float, float], profile: str, minutes: int,
                   start_label: str, client: Optional[httpx.AsyncClient] = None
                   ) -> List[Route]:
    """Up to three candidate loops. Raises GenerationUnavailable on failure -
    never invents a walk to fill the gap."""
    key = api_key()
    if not key:
        raise GenerationUnavailable("Walk generation is not configured on this deployment.")

    own = client is None
    client = client or httpx.AsyncClient(timeout=20.0)
    try:
        async def one(seed: int):
            ors_profile, body = request_body(start, profile, minutes, seed)
            resp = await client.post(ORS_URL.format(profile=ors_profile), json=body,
                                     headers={"Authorization": key})
            if resp.status_code != 200:
                # The detail can carry coordinates; log the status only.
                log.warning("openrouteservice %s for a %s round trip",
                            resp.status_code, ors_profile)
                return None
            feats = resp.json().get("features") or []
            return feats[0] if feats else None

        results = await asyncio.gather(*(one(s) for s in SEEDS), return_exceptions=True)
    finally:
        if own:
            await client.aclose()

    routes = []
    for n, feat in enumerate(results, start=1):
        if isinstance(feat, Exception) or not feat:
            continue
        # "Walk", not "Loop": a round trip can retrace much of itself, and
        # the card names its real shape from the geometry.
        routes.append(route_from_ors(feat, walk_id=f"generated-{n}",
                                     name=f"Walk {n} from {start_label}",
                                     start_label=start_label))
    if not routes:
        raise GenerationUnavailable(
            "Couldn't make walks from here just now. Try again in a moment, "
            "or pick a nearby start.")
    return routes

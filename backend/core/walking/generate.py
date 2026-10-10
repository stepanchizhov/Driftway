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
attribution below. What openrouteservice receives, exactly: the start point
and, for a walk via a checkpoint, the checkpoint - both as precise
coordinates - with the walk options (profile, length, weighting, areas to
avoid). No name, account, device id or label goes with them. A precise start
can still be someone's home, so it is location data about a person; Driftway
neither stores nor logs it (error logs blank every number), but the provider
receives it and handles it under its own terms. Requests go from this server
only, and generated walks are not stored.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import date
from typing import Dict, List, Optional, Tuple

import httpx

from .catalogue import PACE_KMH, Route
from .evidence import Barrier, BarrierKind, Evidence, Section, Status, Surface
from .terrain import attach_gradients, smooth

log = logging.getLogger("driftway")

#: openrouteservice's API host. It moved from api.openrouteservice.org to
#: api.heigit.org/openrouteservice (announced on its forum: the old domain was
#: deprecated from 28 Apr 2026, cut to 10% of plan quota from 27 Aug, due off
#: 28 Sep). Driftway kept calling the old host, and from 10 Oct every request
#: was refused "Quota exceeded" while the dashboard - which counts the new
#: host - showed the quota unused. Overridable with ORS_BASE_URL so the next
#: move is a setting, not a deploy.
ORS_BASE_DEFAULT = "https://api.heigit.org/openrouteservice"


def _ors_url() -> str:
    base = (os.getenv("ORS_BASE_URL") or ORS_BASE_DEFAULT).strip().rstrip("/")
    return base + "/v2/directions/{profile}/geojson"


ORS_URL = _ors_url()
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


#: Every openrouteservice call, across everybody. The free plan allows 40 a
#: minute and 2000 a day; a walk via a checkpoint can now take several calls,
#: so the budget is counted in calls, not in walks requested.
_CALL_BUDGET = None
CALL_WINDOWS = ((60, 35), (86400, 1800))


def _spend() -> None:
    """Count one provider call, or refuse it if the budget is spent."""
    global _CALL_BUDGET
    from core.ratelimit import RateLimited, SlidingWindowLimiter, _Window
    if _CALL_BUDGET is None:
        _CALL_BUDGET = SlidingWindowLimiter()
    try:
        _CALL_BUDGET.check("*", [_Window(a, b) for a, b in CALL_WINDOWS], scope="service")
    except RateLimited:
        raise GenerationUnavailable(
            "Lots of walks are being made just now. Please try again in a minute.")


class ProviderRefused(GenerationUnavailable):
    """The provider would not route at all - its usage limit, or the key.

    Kept apart from "no route": on 10 Oct 2026 openrouteservice answered
    403 {"error": "Quota exceeded"} and the screen said it couldn't find a
    walking route to the checkpoint, as if the place were unreachable.
    """


def refused(resp: httpx.Response) -> Optional[ProviderRefused]:
    """A ProviderRefused for a 401, 403 or 429 answer, else None."""
    if resp.status_code not in (401, 403, 429):
        return None
    try:
        text = str(resp.json().get("error", ""))
    except Exception:  # noqa: BLE001
        text = ""
    if resp.status_code == 429 or "quota" in text.lower():
        # The provider's claim, reported as its claim: on 10 Oct 2026 it said
        # "Quota exceeded" while its dashboard showed 86 of 2000 used.
        return ProviderRefused(
            "The route provider isn't making walks just now: it says its usage "
            "limit has been reached. Try again later; the curated walks still work.")
    return ProviderRefused(
        "The route provider isn't accepting requests from Driftway just now. "
        "The curated walks still work.")


def api_key() -> str:
    return (os.getenv("ORS_API_KEY") or "").strip()


def is_configured() -> bool:
    return bool(api_key())


def target_length_m(minutes: int) -> float:
    """The round-trip length to ask for. A preference, not a promise: the
    result is fitted to the time afterwards, like any other walk."""
    return minutes / 60.0 * PACE_KMH * 1000.0


#: Walk characters openrouteservice can weigh. Documented for foot-* profiles
#: only ("prefer ways through green areas", "prefer quiet ways"); wheelchair
#: routing has no weightings. Rivers, canals, seaside and "town" are not
#: offered by the provider and are not pretended here.
CHARACTERS = ("any", "green", "quiet")


#: How openrouteservice accepts a weighting, learnt from its answers. Its
#: documentation describes the value as an integer but its own example sends
#: {"factor": 0.8}. Measured live on 10 Oct 2026: {"factor": 1.0} is refused
#: (400, code 2002) in Windsor, Heidelberg and Berlin alike; the integer form
#: {"green": 1} is accepted. So the integer form goes first, and the other is
#: kept only as a fallback should the provider change. None until learnt;
#: "none" once both forms have been refused.
_WEIGHT_FORM: Optional[str] = None


def _weight_forms(character: str) -> List[Optional[str]]:
    """Weighting forms to try, best guess first; None means unweighted."""
    if character not in ("green", "quiet") or _WEIGHT_FORM == "none":
        return [None]
    if _WEIGHT_FORM:
        return [_WEIGHT_FORM, None]
    return ["int", "factor", None]


#: The provider's own per-stretch data behind each weighting, asked for with
#: weighted walks so a walk can say when there was nothing to weigh.
WEIGHT_DATA = {"green": "green", "quiet": "noise"}


def flat_weight_data(feature: Dict, character: str) -> bool:
    """True when the provider's data behind a weighting is one value along the
    whole walk - so the weighting had nothing to choose between.

    Measured 10 Oct 2026: around Windsor the "green" and "noise" values came
    back as a single range over 1.7 and 3.4 km routes through park and town,
    and greener and quieter routes were identical to ordinary ones; in Berlin
    and Heidelberg they varied stretch by stretch and the routes changed. A
    walk wholly inside one park could also be flat, so this only says the
    weighting may have changed nothing, never that the data is missing.
    """
    name = WEIGHT_DATA.get(character)
    if not name:
        return False
    values = feature.get("properties", {}).get("extras", {}).get(name, {}).get("values")
    return bool(values) and len({v[2] for v in values}) <= 1


def _ors_error(resp: httpx.Response) -> str:
    """openrouteservice's error code and message, with every number blanked.

    Its error bodies can echo the request, coordinates included, and a log of
    them would record where people were. Digits go; the words stay.
    """
    try:
        err = resp.json().get("error")
    except Exception:  # noqa: BLE001
        return "(no readable body)"
    if isinstance(err, dict):
        code, msg = err.get("code"), str(err.get("message", ""))
    else:
        code, msg = None, str(err)
    return f"code {code}: " + re.sub(r"-?\d+(\.\d+)?", "#", msg)[:200]


def request_body(start: Tuple[float, float], profile: str, minutes: int,
                 seed: int, character: str = "any",
                 weight_form: Optional[str] = "int") -> Tuple[str, Dict]:
    """The ORS profile and request body for one candidate walk.

    A pram normally gets wheelchair routing. Asking for a greener or quieter
    walk switches it to walking routing with steps still avoided, because only
    walking routing can weigh greenery or quiet; the pram rules still judge the
    result, and the walk says which routing made it.
    """
    weighted = character in ("green", "quiet") and weight_form is not None
    ors_profile = "wheelchair" if profile == "pram" and not weighted else "foot-walking"
    body = {
        # ORS takes [longitude, latitude].
        "coordinates": [[start[1], start[0]]],
        "options": {
            "round_trip": {"length": round(target_length_m(minutes)),
                           # More points make rounder walks, per the
                           # docs; fewer retraced stretches.
                           "points": 5, "seed": seed},
        },
        "elevation": True,
        "extra_info": ["surface", "waytype"],
        "instructions": False,
    }
    if profile == "pram":
        body["options"]["avoid_features"] = ["steps"]
    if weighted:
        value = {"factor": 1.0} if weight_form == "factor" else 1
        body["options"]["profile_params"] = {"weightings": {character: value}}
        body["extra_info"] = body["extra_info"] + [WEIGHT_DATA[character]]
    return ors_profile, body


def _haversine(a, b) -> float:
    import math
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


def route_from_ors(feature: Dict, *, walk_id: str, name: str,
                   start_label: str, routing_note: Optional[str] = None) -> Route:
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

    # Along streets and roads: way types 1-3 (state road, road, street).
    total = dist[-1] or 1.0
    on_roads = sum(dist[min(b, len(dist) - 1)] - dist[a]
                   for a, b, v in way_r if v in (1, 2, 3))

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
        ] + ([routing_note] if routing_note else []),
        road_share=round(on_roads / total, 2) if way_r else None,
    )


async def generate(start: Tuple[float, float], profile: str, minutes: int,
                   start_label: str, client: Optional[httpx.AsyncClient] = None,
                   character: str = "any") -> List[Route]:
    """Up to three candidate loops. Raises GenerationUnavailable on failure -
    never invents a walk to fill the gap."""
    key = api_key()
    if not key:
        raise GenerationUnavailable("Walk generation is not configured on this deployment.")

    own = client is None
    client = client or httpx.AsyncClient(timeout=20.0)
    try:
        async def one(seed: int):
            global _WEIGHT_FORM
            for form in _weight_forms(character):
                ors_profile, body = request_body(start, profile, minutes, seed,
                                                 character, form)
                _spend()
                resp = await client.post(ORS_URL.format(profile=ors_profile), json=body,
                                         headers={"Authorization": key})
                if resp.status_code == 200:
                    if form is not None:
                        _WEIGHT_FORM = form
                    elif character in ("green", "quiet") and _WEIGHT_FORM is None:
                        _WEIGHT_FORM = "none"
                    feats = resp.json().get("features") or []
                    return (feats[0] if feats else None), form
                log.warning("openrouteservice %s for a %s round trip (weighting %s) - %s",
                            resp.status_code, ors_profile, form, _ors_error(resp))
                no = refused(resp)
                if no:
                    raise no
                if resp.status_code != 400 or form is None:
                    return None, form
            return None, None

        results = await asyncio.gather(*(one(s) for s in SEEDS), return_exceptions=True)
    finally:
        if own:
            await client.aclose()

    routes = []
    for n, outcome in enumerate(results, start=1):
        if isinstance(outcome, Exception) or not outcome[0]:
            continue
        feat, form = outcome
        weighted = character in ("green", "quiet")
        wanted = "greener" if character == "green" else "quieter"
        notes = []
        if weighted and form is None:
            notes.append(f"{wanted.capitalize()} routing wasn't accepted by the route "
                         "provider, so this is an ordinary walk.")
        elif weighted and flat_weight_data(feat, character):
            what = "greenery" if character == "green" else "traffic-noise"
            notes.append(f"The route provider's {what} data doesn't vary along this "
                         f"walk, so asking for a {wanted} walk may not have changed it.")
        if weighted and form is not None and profile == "pram":
            notes.append("Made with walking routes, steps avoided, so it could favour "
                         f"{wanted} ways; wheelchair routing cannot weigh that.")
        note = " ".join(notes) or None
        # "Walk", not "Loop": a round trip can retrace much of itself, and
        # the card names its real shape from the geometry.
        routes.append(route_from_ors(
            feat, walk_id=f"generated-{n}", name=f"Walk {n} from {start_label}",
            start_label=start_label, routing_note=note))
    if character in ("green", "quiet"):
        # Asked for less road: put the walks with the least of it first.
        routes.sort(key=lambda r: r.road_share if r.road_share is not None else 1.0)
    if not routes:
        no = next((o for o in results if isinstance(o, ProviderRefused)), None)
        if no:
            raise no
        raise GenerationUnavailable(
            "Couldn't make walks from here just now. Try again in a moment, "
            "or pick a nearby start.")
    return routes


# ------------------------------------------------------------- via a place

#: Half-width of the corridor the way back is asked to avoid.
CORRIDOR_HALF_M = 25.0
#: Left open at each end of the outward route, where the two must meet.
CORRIDOR_OPEN_M = 150.0
#: Most corridor pieces sent; the outward line is thinned to this many.
CORRIDOR_PIECES = 40


def corridor(coords: List[List[float]]) -> Optional[Dict]:
    """A GeoJSON MultiPolygon hugging an outward route, for the way back to avoid.

    Each piece is a thin rectangle around one stretch of the line. The first
    and last CORRIDOR_OPEN_M are left out: the way back has to leave the
    checkpoint and reach the start, both of which lie on the outward route.
    `coords` are ORS [lng, lat, ...] points.
    """
    import math
    pts = [(c[1], c[0]) for c in coords]
    dist = [0.0]
    for a, b in zip(pts, pts[1:]):
        dist.append(dist[-1] + _haversine(a, b))
    total = dist[-1]
    keep = [p for p, d in zip(pts, dist)
            if CORRIDOR_OPEN_M <= d <= total - CORRIDOR_OPEN_M]
    if len(keep) < 2:
        return None
    step = max(1, math.ceil((len(keep) - 1) / CORRIDOR_PIECES))
    keep = keep[::step] + ([keep[-1]] if (len(keep) - 1) % step else [])
    polys = []
    for (la1, lo1), (la2, lo2) in zip(keep, keep[1:]):
        k = math.cos(math.radians((la1 + la2) / 2))
        dx, dy = (lo2 - lo1) * k, la2 - la1
        n = math.hypot(dx, dy)
        if n == 0:
            continue
        # Unit normal, in degrees of latitude per metre of half-width.
        off = CORRIDOR_HALF_M / 111320.0
        nx, ny = -dy / n * off, dx / n * off
        ring = [[lo1 + nx / k, la1 + ny], [lo2 + nx / k, la2 + ny],
                [lo2 - nx / k, la2 - ny], [lo1 - nx / k, la1 - ny],
                [lo1 + nx / k, la1 + ny]]
        polys.append([[[round(x, 6), round(y, 6)] for x, y in ring]])
    return {"type": "MultiPolygon", "coordinates": polys} if polys else None


def join_features(out: Dict, back: Dict) -> Dict:
    """One feature from an outward and a return route, extras re-indexed."""
    oc = out["geometry"]["coordinates"]
    bc = back["geometry"]["coordinates"]
    shift = len(oc) - 1                 # the checkpoint point is shared
    extras: Dict = {}
    for name in ("surface", "waytype"):
        ov = out.get("properties", {}).get("extras", {}).get(name, {}).get("values", [])
        bv = back.get("properties", {}).get("extras", {}).get(name, {}).get("values", [])
        extras[name] = {"values": [list(v) for v in ov]
                        + [[a + shift, b + shift, v] for a, b, v in bv]}
    return {"type": "Feature",
            "geometry": {"type": "LineString", "coordinates": oc + bc[1:]},
            "properties": {"extras": extras}}


# ------------------------------------------------------------ checkpoints
#
# A checkpoint means "visit this point", not "follow this avenue". The parent
# places it by search or on the map; openrouteservice then snaps it to the
# nearest way the chosen profile may use - for a pram, wheelchair routing, so
# never onto steps. What the provider snapped to is the point the walk really
# visits, and it is reported, never hidden. Policy, decided 10 Oct 2026:
#
#   * within CHECKPOINT_ON_ROUTE_M of the marker, the walk visits the marker;
#   * further, up to CHECKPOINT_SEARCH_M, the walks are made but the parent is
#     shown the moved point and must accept it first. Distance alone does not
#     show the two places are equivalent - the nearest path may be across a
#     river or behind a fence - so the parent decides, with both on the map;
#   * beyond CHECKPOINT_SEARCH_M nothing is routed and the parent is asked to
#     move the marker. No connector is ever drawn across unmapped ground.
#
# 25 m is a HYPOTHESIS: about a path's width plus a marker placed by finger.
# A fence or a river narrower than that could still separate marker and path.
#
# How close is close enough is the parent's to set (founder decision, 10 Oct
# 2026): a walk along the Long Walk "via" the King George III statue need not
# climb Snow Hill to it - passing 200 m to the side is the walk they mean. With
# a reach above 25 m the way out is cut where it first comes within that
# distance of the marker, the way back starts from there, the provider may
# look that far for a path, and only a walk that cannot get that close needs
# the parent's acceptance.

#: The walk counts as visiting the checkpoint within this distance of it -
#: the default, and the least a parent can choose.
CHECKPOINT_ON_ROUTE_M = 25.0
#: The most a parent can choose: further, and it is no longer a checkpoint.
CHECKPOINT_REACH_MAX_M = 500
#: How far openrouteservice may look for a usable way near the checkpoint.
CHECKPOINT_SEARCH_M = 150
#: How far it may look near the start: its own documented default for
#: directions (maintainer note, GIScience/openrouteservice#1798), unchanged.
START_SEARCH_M = 400
#: Closer than this to the start, there is nowhere to walk out to.
CHECKPOINT_MIN_M = 50.0


class CheckpointProblem(GenerationUnavailable):
    """The checkpoint itself is the problem; the parent can fix it.

    `code` is one of "too_close", "too_far", "unreachable", "no_route";
    `minimum_minutes` is set for "too_far".
    """

    def __init__(self, code: str, message: str, minimum_minutes: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.minimum_minutes = minimum_minutes


def fit_tolerance(minutes: float) -> float:
    """The catalogue's own "about right" band, used for conflicts too."""
    return max(5.0, 0.15 * minutes)


def minimum_via_minutes(start: Tuple[float, float], via: Tuple[float, float],
                        reach_m: float = CHECKPOINT_ON_ROUTE_M) -> float:
    """No walk out to within `reach_m` of a point and back can be shorter than
    the straight line there and back. A floor, not an estimate: real paths are
    longer."""
    beyond = max(0.0, _haversine(start, via) - max(reach_m, CHECKPOINT_ON_ROUTE_M))
    return 2 * beyond / 1000.0 / PACE_KMH * 60.0


def check_checkpoint(start: Tuple[float, float], via: Tuple[float, float],
                     minutes: Optional[int], via_label: str,
                     reach_m: float = CHECKPOINT_ON_ROUTE_M) -> None:
    """Refuse, before any provider call, a checkpoint that cannot work."""
    if _haversine(start, via) - max(reach_m, CHECKPOINT_ON_ROUTE_M) < CHECKPOINT_MIN_M:
        if reach_m > CHECKPOINT_ON_ROUTE_M:
            raise CheckpointProblem(
                "too_close", f"Your start is already within about {round(reach_m)} m of "
                f"{via_label}, so there is nowhere to walk out to. Choose a point "
                "further away, or ask for the walk to come closer to it.")
        raise CheckpointProblem(
            "too_close", f"{via_label} is right by your start, so there is nowhere "
            "to walk out to. Choose a point further away.")
    if minutes:
        floor = minimum_via_minutes(start, via, reach_m)
        if floor > minutes + fit_tolerance(minutes):
            need = int(-(-floor // 1))                   # up to the whole minute
            raise CheckpointProblem(
                "too_far", f"Getting to {via_label} and back takes at least "
                f"{need} minutes in a straight line, longer than the {minutes} you "
                "asked for. Choose a longer time or a nearer checkpoint.",
                minimum_minutes=need)


def _ors_failure(resp: httpx.Response) -> Tuple[Optional[int], Optional[int]]:
    """openrouteservice's error code and, for "point not found", which point.

    Read here, never logged: the message carries the coordinates.
    """
    try:
        err = resp.json().get("error")
    except Exception:  # noqa: BLE001
        return None, None
    if not isinstance(err, dict):
        return None, None
    # Live wording, 10 Oct 2026: "Could not find routable point within a
    # radius of 150.0 meters of specified coordinate 1: <lng> <lat>." Older
    # releases said "Could not find point 1: ..."; both are read.
    m = re.search(r"(?:specified coordinate|point) (\d+)", str(err.get("message", "")))
    return err.get("code"), (int(m.group(1)) if m else None)


def closest_m(line: List[List[float]], point: Tuple[float, float]) -> float:
    """Closest approach, in metres, of an ORS [lng, lat] line to a (lat, lng)
    point - along segments, not only at vertices."""
    import math
    k = math.cos(math.radians(point[0]))
    px, py = point[1] * k * 111320.0, point[0] * 111320.0
    pts = [(c[0] * k * 111320.0, c[1] * 111320.0) for c in line]
    if len(pts) == 1:
        return math.hypot(pts[0][0] - px, pts[0][1] - py)
    best = float("inf")
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
        best = min(best, math.hypot(ax + t * dx - px, ay + t * dy - py))
    return best


def approach(coords: List[List[float]], point: Tuple[float, float],
             reach_m: float) -> Optional[Tuple[int, List[float]]]:
    """Where an ORS [lng, lat, ele] line first comes within `reach_m` of a
    (lat, lng) point: (index of the segment's first vertex, the entry point,
    interpolated - height included - on that segment). None if it never does.
    """
    import math
    k = math.cos(math.radians(point[0]))

    def xy(c):
        return ((c[0] - point[1]) * k * 111320.0, (c[1] - point[0]) * 111320.0)

    if math.hypot(*xy(coords[0])) <= reach_m:
        return 0, list(coords[0])
    for i, (a, b) in enumerate(zip(coords, coords[1:])):
        (ax, ay), (bx, by) = xy(a), xy(b)
        dx, dy = bx - ax, by - ay
        # |A + t(B - A)| = r, smallest t in [0, 1].
        qa = dx * dx + dy * dy
        qb = 2 * (ax * dx + ay * dy)
        qc = ax * ax + ay * ay - reach_m * reach_m
        disc = qb * qb - 4 * qa * qc
        if qa == 0 or disc < 0:
            continue
        t = (-qb - math.sqrt(disc)) / (2 * qa)
        if 0.0 <= t <= 1.0:
            entry = [a[j] + t * (b[j] - a[j]) for j in range(min(len(a), len(b)))]
            return i, entry
    return None


def cut_feature(feat: Dict, index: int, entry: List[float]) -> Dict:
    """The feature up to and including `entry`, which lies on the segment
    starting at vertex `index`; per-stretch extras clipped to match."""
    coords = feat["geometry"]["coordinates"][:index + 1] + [entry]
    last = len(coords) - 1
    extras: Dict = {}
    for name, block in feat.get("properties", {}).get("extras", {}).items():
        vals = [[a, min(b, last), v] for a, b, v in block.get("values", []) if a < last]
        extras[name] = {**block, "values": vals}
    return {"type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {**feat.get("properties", {}), "extras": extras}}


#: Different loops through one checkpoint to look for.
VIA_VARIANTS = 3
#: A candidate sharing more than this much of its line with one already found
#: is the same walk again and is dropped.
DUPLICATE_SHARE = 0.8


def _overlap(a: List[List[float]], b: List[List[float]]) -> float:
    """Share of line `a` (ORS [lng, lat] points) lying within 25 m of line `b`."""
    if not a or not b:
        return 0.0
    step_a = max(1, len(a) // 80)
    step_b = max(1, len(b) // 300)
    pa = [(p[1], p[0]) for p in a[::step_a]]
    pb = [(p[1], p[0]) for p in b[::step_b]]
    near = sum(1 for x in pa if any(_haversine(x, y) <= 25.0 for y in pb))
    return near / len(pa)


def _merge(*polys: Optional[Dict]) -> Optional[Dict]:
    pieces = [c for p in polys if p for c in p["coordinates"]]
    return {"type": "MultiPolygon", "coordinates": pieces} if pieces else None


async def via_walk(start: Tuple[float, float], via: Tuple[float, float],
                   profile: str, start_label: str, via_label: str,
                   character: str = "any",
                   client: Optional[httpx.AsyncClient] = None,
                   minutes: Optional[int] = None,
                   reach_m: float = CHECKPOINT_ON_ROUTE_M) -> List[Route]:
    """Up to three different walks out to a chosen place and back.

    Founder requests, 9 Oct: a checkpoint to build walks around, and more than
    one way to do it - a known route along a treeline never came up, because
    only the shortest way out and the shortest different way back were asked
    for. Each further variant is told to avoid the paths the earlier ones used
    (openrouteservice's documented avoid_polygons, as narrow corridors left
    open near the start and the checkpoint), so it comes back genuinely
    different; a candidate that repeats an earlier one anyway is dropped.

    The first variant may go over some of the same ground if no wholly
    different way back exists - a single bridge or gate can force that - and
    says so; the parent's retracing preference then decides, in the open,
    whether it is shown. Later variants are only kept if they are real
    alternatives. Every variant kept passes within CHECKPOINT_ON_ROUTE_M of
    the point the provider routed to, and each Route's `via` records that
    point, the parent's own marker and the distance between them.

    With `reach_m` above CHECKPOINT_ON_ROUTE_M the walk need only come that
    close: each way out is cut where it first does, and the way back starts
    there.

    Raises CheckpointProblem when the checkpoint is the problem (too close,
    too far for the time, no usable way near it, no route to it).
    """
    key = api_key()
    if not key:
        raise GenerationUnavailable("Walk generation is not configured on this deployment.")
    reach_m = min(max(float(reach_m), CHECKPOINT_ON_ROUTE_M), CHECKPOINT_REACH_MAX_M)
    passing = reach_m > CHECKPOINT_ON_ROUTE_M
    search_m = max(CHECKPOINT_SEARCH_M, int(reach_m))
    check_checkpoint(start, via, minutes, via_label, reach_m)
    forms = _weight_forms(character)

    def make_base(form):
        p, b = request_body(start, profile, 30, 1, character, form)
        b["options"].pop("round_trip", None)
        return p, b

    def body(base, a, b, avoid=None):
        # Both legs keep the profile's own options - steps avoided for a pram -
        # so the way back is held to the same access rules as the way out.
        req = {**base, "coordinates": [[a[1], a[0]], [b[1], b[0]]],
               "radiuses": ([START_SEARCH_M, search_m] if a == start
                            else [search_m, START_SEARCH_M]),
               "options": dict(base["options"])}
        if avoid:
            req["options"]["avoid_polygons"] = avoid
        return req

    own = client is None
    client = client or httpx.AsyncClient(timeout=20.0)
    headers = {"Authorization": key}
    found: List[Tuple[Dict, Optional[str]]] = []
    used: List[Dict] = []        # corridors of every line found so far
    dropped = 0

    async def post(url, req):
        _spend()
        return await client.post(url, json=req, headers=headers)

    def feature(resp):
        if resp.status_code == 200 and resp.json().get("features"):
            return resp.json()["features"][0]
        return None

    try:
        # The way out for the first variant, learning which weighting form works.
        for form in forms:
            ors_profile, base = make_base(form)
            url = ORS_URL.format(profile=ors_profile)
            r1 = await post(url, body(base, start, via))
            if r1.status_code != 400 or form is None:
                break
            log.warning("openrouteservice 400 for the way to a checkpoint "
                        "(weighting %s) - %s", form, _ors_error(r1))
        no = refused(r1)
        if no:
            log.warning("openrouteservice %s for the way to a checkpoint - %s",
                        r1.status_code, _ors_error(r1))
            raise no
        first_out = feature(r1)
        if first_out is None:
            log.warning("openrouteservice %s for the way to a checkpoint - %s",
                        r1.status_code, _ors_error(r1))
            code, point = _ors_failure(r1)
            what = {"pram": "a pram", "carrier": "walking with a carrier",
                    "walker": "walking"}.get(profile, "walking")
            if code == 2010 and point == 1:
                raise CheckpointProblem(
                    "unreachable", f"There's no mapped way suitable for {what} "
                    f"within {search_m} m of {via_label}. Move the "
                    "checkpoint onto or near a path.")
            if code == 2010 and point == 0:
                raise GenerationUnavailable(
                    "There's no mapped path near your start. Choose a start on "
                    "or near a path.")
            if code == 2009:
                raise CheckpointProblem(
                    "no_route", f"No route suitable for {what} reaches {via_label} "
                    "from your start. It may be on private land, across water, "
                    "or reachable only by steps. Try a different point.")
            raise GenerationUnavailable(f"Couldn't find a walking route to {via_label}.")

        def turn(out):
            """The way out, cut where it first comes within reach when the
            parent allows passing at a distance, and the point to turn at."""
            cs = out["geometry"]["coordinates"]
            hit = approach(cs, via, reach_m) if passing else None
            if hit and hit[0] + 1 < len(cs):
                out = cut_feature(out, *hit)
            end = out["geometry"]["coordinates"][-1]
            return out, (end[1], end[0])

        # Where the walk really turns: where the provider took the way out,
        # or where it first came close enough.
        first_out, routed = turn(first_out)
        close_enough = _haversine(via, routed) <= reach_m + 1.0

        for k in range(VIA_VARIANTS):
            if k == 0:
                out, at = first_out, routed
            else:
                out = feature(await post(url, body(base, start, via, _merge(*used))))
                if out is None:
                    break
                out, at = turn(out)
            out_line = corridor(out["geometry"]["coordinates"])
            back = feature(await post(url, body(base, at, start, _merge(out_line, *used))))
            if back is None and used:
                back = feature(await post(url, body(base, at, start, out_line)))
            note = None
            if back is None and k == 0:
                back = feature(await post(url, body(base, at, start)))
                if back is None:
                    raise GenerationUnavailable(f"Couldn't find a way back from {via_label}.")
                note = (f"No way back from {via_label} that avoids the way out was "
                        "found. A single bridge, gate or path can force that, so "
                        "this walk goes over some of the same ground twice; the "
                        "card says how much.")
            if back is None:
                break
            joined = join_features(out, back)
            line = joined["geometry"]["coordinates"]
            # Kept only if it really comes close enough: within the parent's
            # reach of their marker, or - when even the first walk could not,
            # and the parent must accept a moved point - within 25 m of that.
            missed = (closest_m(line, via) > reach_m + 1.0 if close_enough
                      else closest_m(line, routed) > CHECKPOINT_ON_ROUTE_M)
            if missed:
                dropped += 1
                continue
            if any(_overlap(line, j["geometry"]["coordinates"]) > DUPLICATE_SHARE
                   for j, _, _ in found):
                break
            found.append((joined, note, at))
            used += [c for c in (out_line, corridor(back["geometry"]["coordinates"])) if c]
    except CheckpointProblem:
        raise
    except GenerationUnavailable:
        if not found:
            raise
    finally:
        if own:
            await client.aclose()

    if dropped:
        log.info("checkpoint walks: %d variant(s) dropped for missing the checkpoint",
                 dropped)
    routes = []
    for n, (joined, note, at) in enumerate(found, start=1):
        if passing and close_enough:
            pass_note = (f"Turns back about {round(_haversine(via, at))} m from "
                         f"{via_label}, as close as you asked it to come.")
            note = f"{note} {pass_note}" if note else pass_note
        r = route_from_ors(joined, walk_id=f"via-{n}",
                           name=f"Via {via_label}" + (f", option {n}" if n > 1 else ""),
                           start_label=start_label, routing_note=note)
        r.via = {"lat": at[0], "lng": at[1], "label": via_label,
                 "requested": {"lat": via[0], "lng": via[1]},
                 "offset_m": round(_haversine(via, at)), "reach_m": round(reach_m)}
        routes.append(r)
    return routes

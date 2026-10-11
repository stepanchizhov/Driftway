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

from .catalogue import Route, pace_kmh
from .evidence import Barrier, BarrierKind, Evidence, Section, Status, Surface
from .terrain import attach_gradients, smooth

log = logging.getLogger("driftway")

#: openrouteservice's API host. It moved from api.openrouteservice.org to
#: api.heigit.org/openrouteservice (announced on its forum: the old domain was
#: deprecated from 28 Apr 2026, cut to 10% of plan quota from 27 Aug, due off
#: 28 Sep). Driftway kept calling the old host, and from 10 Oct every request
#: was refused "Quota exceeded" while the dashboard - which counts the new
#: host - showed the quota unused. The address, a fallback address and the
#: shared call budget live in core/ors.py; ORS_BASE_URL changes the address
#: without a deploy.
from core import ors  # noqa: E402

DIRECTIONS_PATH = "/v2/directions/{profile}/geojson"


def _ors_url() -> str:
    return ors.base_url() + DIRECTIONS_PATH


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


def _spend() -> None:
    """Count one provider call against the directions budget shared with the
    driving fallback (core/ors.py), or refuse it if that is spent. Counted in
    calls, not walks: a walk via a checkpoint can take several."""
    try:
        ors.spend("directions")
    except ors.OrsBudgetSpent:
        raise GenerationUnavailable(
            "Lots of walks are being made just now. Please try again in a minute.")


def pram_character(profile: str, character: str) -> Tuple[str, Optional[str]]:
    """The walk character actually used, and a note when a request was
    changed. A pram keeps its pram routing: Greener and Quieter need walking
    routing, which drops the pram's rules, so they are not offered for a pram
    and a request for them (from an older app) is answered with an ordinary
    pram walk that says so - never silently with weaker rules."""
    if profile == "pram" and character in ("green", "quiet"):
        return "any", ("Greener and Quieter aren't available with a pram: they need "
                       "walking routes, which don't keep the pram's rules on surface, "
                       "slope and kerbs. This walk was made with pram routing.")
    return character, None


async def _post(client: httpx.AsyncClient, ors_profile: str, body: Dict) -> httpx.Response:
    """One directions call, already counted, with the fallback address."""
    return await ors.request(client, "POST", DIRECTIONS_PATH.format(profile=ors_profile),
                             "directions", count=False, json=body)


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
    return minutes / 60.0 * pace_kmh() * 1000.0


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
                 weight_form: Optional[str] = "int",
                 length_m: Optional[float] = None) -> Tuple[str, Dict]:
    """The ORS profile and request body for one candidate walk.

    A pram always gets wheelchair routing. Until 0.8, asking for a greener or
    quieter pram walk switched it to walking routing with only steps avoided,
    because only walking routing can weigh greenery or quiet. That was a
    weaker rule set, not the same one: wheelchair routing also restricts
    surface, smoothness, slope and kerb height, so the switch could admit
    paths a pram may not manage. Preferences must not weaken a profile's
    access rules (product rule, restated 10 Oct 2026), so a pram is never
    weighted here, whatever the caller asks.
    """
    weighted = (character in ("green", "quiet") and weight_form is not None
                and profile != "pram")
    ors_profile = "wheelchair" if profile == "pram" else "foot-walking"
    body = {
        # ORS takes [longitude, latitude].
        "coordinates": [[start[1], start[0]]],
        "options": {
            "round_trip": {"length": round(length_m or target_length_m(minutes)),
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


# ------------------------------------------------------------ spikes and fit
#
# Founder feedback, 11 Oct 2026: generated walks came back much longer than
# asked and still ranked first, and some had spikes - a stretch out along a
# path and straight back the same way, adding time and nothing else. So a
# round trip is first cleaned of spikes, then measured in walking minutes;
# one that misses the time by more than FIT_RETRY_SHARE is asked for once more
# with its length scaled; and the results are ordered with walks within
# FIT_RANK_SHARE of the time first.

#: A spike is at most this long, out and back together.
SPIKE_MAX_M = 700.0
#: Shorter than this is GPS-scale wobble, not a spike.
SPIKE_MIN_M = 40.0
#: The two ends of a spike lie this close together.
SPIKE_JOIN_M = 15.0
#: The way back along a spike lies this close to the way out.
SPIKE_TRACK_M = 20.0
#: A spike is never more than this share of the whole walk.
SPIKE_MAX_SHARE = 0.4

#: Ask again when a loop misses the time by more than this share.
FIT_RETRY_SHARE = 0.15
#: Walks within this share of the time rank above every walk outside it.
FIT_RANK_SHARE = 0.20


#: How far either side of a spike to look, to see which way the walk goes on.
SPIKE_CONTEXT_M = 30.0


def _is_spike(pts: List[Tuple[float, float]], i: int, j: int,
              cum: Optional[List[float]] = None) -> bool:
    """Whether pts[i..j] goes out and comes back along itself, and the walk
    then carries on somewhere new.

    The second half matters: the far end of a there-and-back walk also goes
    out and comes back, but then the walk heads back the way it came. That
    is the walk's turning point, not a spike, and must not be cut.
    """
    if cum is not None:
        before = next((k for k in range(i, -1, -1) if cum[i] - cum[k] >= SPIKE_CONTEXT_M), None)
        after = next((k for k in range(j, len(pts)) if cum[k] - cum[j] >= SPIKE_CONTEXT_M), None)
        if (before is not None and after is not None
                and _haversine(pts[before], pts[after]) <= SPIKE_TRACK_M):
            return False
    seg = pts[i:j + 1]
    far = max(range(len(seg)), key=lambda k: _haversine(seg[0], seg[k]))
    if far == 0 or far == len(seg) - 1 or _haversine(seg[0], seg[far]) < SPIKE_TRACK_M:
        return False
    out, back = seg[:far + 1], seg[far:]
    near = sum(1 for p in back if any(_haversine(p, q) <= SPIKE_TRACK_M for q in out))
    return near / len(back) >= 0.85


def despike(feature: Dict) -> Tuple[Dict, float]:
    """The feature with its spikes cut out, and how many metres went.

    Keeps point i and jumps straight to j where pts[i..j] is a spike: the two
    ends are within SPIKE_JOIN_M on the same path, so the walk stays
    continuous. Per-stretch extras are re-indexed to match.
    """
    import bisect
    coords = feature["geometry"]["coordinates"]
    pts = [(c[1], c[0]) for c in coords]
    n = len(pts)
    if n < 6:
        return feature, 0.0
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + _haversine(a, b))
    total = cum[-1] or 1.0
    keep: List[int] = []
    i = 0
    while i < n:
        keep.append(i)
        best = None
        j = i + 2
        while j < n and cum[j] - cum[i] <= min(SPIKE_MAX_M, SPIKE_MAX_SHARE * total):
            if (cum[j] - cum[i] >= SPIKE_MIN_M
                    and _haversine(pts[i], pts[j]) <= SPIKE_JOIN_M
                    and not (i == 0 and j == n - 1)
                    and _is_spike(pts, i, j, cum)):
                best = j
            j += 1
        i = best if best is not None else i + 1
    removed = sum(cum[b] - cum[a] for a, b in zip(keep, keep[1:]) if b > a + 1
                  ) - sum(_haversine(pts[a], pts[b]) for a, b in zip(keep, keep[1:]) if b > a + 1)
    if len(keep) == n:
        return feature, 0.0

    def new(p: int) -> int:
        return min(bisect.bisect_left(keep, p), len(keep) - 1)

    extras: Dict = {}
    for name, block in feature.get("properties", {}).get("extras", {}).items():
        vals = []
        for a, b, v in block.get("values", []):
            na, nb = new(a), new(b)
            if nb > na:
                vals.append([na, nb, v])
        extras[name] = {**block, "values": vals}
    out = {"type": "Feature",
           "geometry": {"type": "LineString", "coordinates": [coords[k] for k in keep]},
           "properties": {**feature.get("properties", {}), "extras": extras}}
    return out, removed


def walk_minutes(feature: Dict) -> float:
    """The walk's time, measured the way its card measures it."""
    from .catalogue import _full_minutes
    return _full_minutes(route_from_ors(feature, walk_id="m", name="m", start_label="m"))


def fit_rank(minutes_actual: float, minutes_asked: int) -> Tuple[int, float]:
    """Sort key: walks within FIT_RANK_SHARE of the time first, then the
    smaller miss."""
    miss = abs(minutes_actual - minutes_asked) / max(1, minutes_asked)
    return (0 if miss <= FIT_RANK_SHARE else 1, miss)


async def generate(start: Tuple[float, float], profile: str, minutes: int,
                   start_label: str, client: Optional[httpx.AsyncClient] = None,
                   character: str = "any") -> List[Route]:
    """Up to three candidate loops. Raises GenerationUnavailable on failure -
    never invents a walk to fill the gap."""
    key = api_key()
    if not key:
        raise GenerationUnavailable("Walk generation is not configured on this deployment.")
    character, pram_note = pram_character(profile, character)

    own = client is None
    client = client or httpx.AsyncClient(timeout=20.0)
    try:
        async def one(seed: int, length_m: Optional[float] = None):
            global _WEIGHT_FORM
            for form in _weight_forms(character):
                ors_profile, body = request_body(start, profile, minutes, seed,
                                                 character, form, length_m=length_m)
                _spend()
                resp = await _post(client, ors_profile, body)
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

        results = list(await asyncio.gather(*(one(s) for s in SEEDS),
                                            return_exceptions=True))

        def measured(outcome):
            """(feature without spikes, form, minutes), or None."""
            if isinstance(outcome, Exception) or not outcome or not outcome[0]:
                return None
            feat, form = outcome
            feat, _ = despike(feat)
            return feat, form, walk_minutes(feat)

        found = [measured(o) for o in results]
        # One more ask for each loop that misses the time by more than
        # FIT_RETRY_SHARE, its length scaled by the miss; keep the closer.
        asked_m = target_length_m(minutes)
        retry = [(k, m) for k, m in enumerate(found)
                 if m and abs(m[2] - minutes) / minutes > FIT_RETRY_SHARE]
        if retry:
            again = await asyncio.gather(
                *(one(SEEDS[k], asked_m * max(0.5, min(1.6, minutes / m[2])))
                  for k, m in retry),
                return_exceptions=True)
            for (k, old), outcome in zip(retry, again):
                new = measured(outcome)
                if new and abs(new[2] - minutes) < abs(old[2] - minutes):
                    found[k] = new
    except ProviderRefused:
        raise
    finally:
        if own:
            await client.aclose()

    # Walks that fit the time first (founder feedback, 11 Oct); then, for a
    # greener or quieter request, the least road among equals.
    def order(m):
        feat = m[0]
        way = [v for a, b, v in feat.get("properties", {}).get("extras", {})
               .get("waytype", {}).get("values", [])]
        roads = sum(1 for v in way if v in (1, 2, 3)) / max(1, len(way))
        return fit_rank(m[2], minutes) + ((roads,) if character in ("green", "quiet") else ())

    ordered = sorted((m for m in found if m), key=order)
    routes = []
    for n, (feat, form, _mins) in enumerate(ordered, start=1):
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
        if pram_note:
            notes.append(pram_note)
        note = " ".join(notes) or None
        # "Walk", not "Loop": a round trip can retrace much of itself, and
        # the card names its real shape from the geometry.
        routes.append(route_from_ors(
            feat, walk_id=f"generated-{n}", name=f"Walk {n} from {start_label}",
            start_label=start_label, routing_note=note))
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


def corridor(coords: List[List[float]],
             open_near: Optional[List[Tuple[float, float]]] = None) -> Optional[Dict]:
    """A GeoJSON MultiPolygon hugging an outward route, for the way back to avoid.

    Each piece is a thin rectangle around one stretch of the line. The first
    and last CORRIDOR_OPEN_M are left out: the way back has to leave the
    checkpoint and reach the start, both of which lie on the outward route.
    Stretches within CORRIDOR_OPEN_M of any (lat, lng) in `open_near` are left
    out too - every checkpoint, so a later walk can still reach them all.
    `coords` are ORS [lng, lat, ...] points.
    """
    import math
    pts = [(c[1], c[0]) for c in coords]
    dist = [0.0]
    for a, b in zip(pts, pts[1:]):
        dist.append(dist[-1] + _haversine(a, b))
    total = dist[-1]
    keep = [p for p, d in zip(pts, dist)
            if CORRIDOR_OPEN_M <= d <= total - CORRIDOR_OPEN_M
            and not any(_haversine(p, q) < CORRIDOR_OPEN_M for q in (open_near or []))]
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
    return 2 * beyond / 1000.0 / pace_kmh() * 60.0


#: Most checkpoints in one walk (founder request, 11 Oct 2026).
MAX_CHECKPOINTS = 3


def minimum_chain_minutes(start: Tuple[float, float], pins: List[Tuple[float, float]],
                          reach_m: float = CHECKPOINT_ON_ROUTE_M) -> float:
    """A floor for a walk from the start through every checkpoint, in order,
    and home. Passing within r of a point P on the way from A to B costs at
    least |AP| + |PB| - 2r, so each checkpoint takes 2r off the straight-line
    chain. A floor, not an estimate."""
    chain = [start, *pins, start]
    straight = sum(_haversine(a, b) for a, b in zip(chain, chain[1:]))
    beyond = max(0.0, straight - 2 * max(reach_m, CHECKPOINT_ON_ROUTE_M) * len(pins))
    return beyond / 1000.0 / pace_kmh() * 60.0


def check_checkpoints(start: Tuple[float, float], pins: List[Tuple[float, float]],
                      minutes: Optional[int], labels: List[str],
                      reach_m: float = CHECKPOINT_ON_ROUTE_M) -> None:
    """Refuse, before any provider call, checkpoints that cannot work: the
    first one at the start, two in the same place, or a chain too long for
    the time."""
    if len(pins) > 1:
        check_checkpoint(start, pins[0], None, labels[0], reach_m)
        for (a, la), (b, lb) in zip(zip(pins, labels), zip(pins[1:], labels[1:])):
            if _haversine(a, b) < CHECKPOINT_MIN_M:
                raise CheckpointProblem(
                    "too_close", f"{la} and {lb} are almost the same place. Move one "
                    "of them, or remove it.")
        if minutes:
            floor = minimum_chain_minutes(start, pins, reach_m)
            if floor > minutes + fit_tolerance(minutes):
                need = int(-(-floor // 1))
                raise CheckpointProblem(
                    "too_far", f"Going through all {len(pins)} checkpoints and back "
                    f"takes at least {need} minutes in a straight line, longer than "
                    f"the {minutes} you asked for. Choose a longer time, or nearer or "
                    "fewer checkpoints.", minimum_minutes=need)
        return
    check_checkpoint(start, pins[0], minutes, labels[0], reach_m)


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


def splice(feat: Dict, a: int, b: int, mid: Dict) -> Dict:
    """`feat` with its points a..b replaced by `mid`'s line, extras re-indexed."""
    cs = feat["geometry"]["coordinates"]
    ms = mid["geometry"]["coordinates"]
    coords = cs[:a] + ms + cs[b + 1:]
    shift = a + len(ms) - 1 - b              # how far points after b move
    extras: Dict = {}
    for name in ("surface", "waytype"):
        vals = []
        for x, y, v in feat.get("properties", {}).get("extras", {}).get(name, {}).get("values", []):
            if x < a:
                vals.append([x, min(y, a), v])
        for x, y, v in mid.get("properties", {}).get("extras", {}).get(name, {}).get("values", []):
            vals.append([x + a, y + a, v])
        for x, y, v in feat.get("properties", {}).get("extras", {}).get(name, {}).get("values", []):
            if y > b:
                vals.append([max(x, b) + shift, y + shift, v])
        extras[name] = {"values": [v for v in vals if v[1] > v[0]]}
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {**feat.get("properties", {}), "extras": extras}}


def pin_indices(feat: Dict, pins: List[Tuple[float, float]]) -> List[int]:
    """Where on the line each checkpoint was routed to: the provider's own
    `way_points` when it sends them, else the nearest point after the last."""
    cs = feat["geometry"]["coordinates"]
    wp = feat.get("properties", {}).get("way_points")
    if isinstance(wp, list) and len(wp) == len(pins) + 1:
        return [min(int(i), len(cs) - 1) for i in wp[1:]]
    out, after = [], 0
    for p in pins:
        k = min(range(after, len(cs)), key=lambda i: _haversine((cs[i][1], cs[i][0]), p))
        out.append(k)
        after = k
    return out


def chain_name(labels: List[str]) -> str:
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " and " + labels[-1]


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


async def via_walk(start: Tuple[float, float], via,
                   profile: str, start_label: str, via_label,
                   character: str = "any",
                   client: Optional[httpx.AsyncClient] = None,
                   minutes: Optional[int] = None,
                   reach_m: float = CHECKPOINT_ON_ROUTE_M) -> List[Route]:
    """Up to three different walks through one to three chosen places, in
    order, and back home another way.

    Founder requests, 9 Oct: a checkpoint to build walks around, and more than
    one way to do it - a known route along a treeline never came up, because
    only the shortest way out and the shortest different way back were asked
    for. Each further variant is told to avoid the paths the earlier ones used
    (openrouteservice's documented avoid_polygons, as narrow corridors left
    open near the start and every checkpoint), so it comes back genuinely
    different; a candidate that repeats an earlier one anyway is dropped.
    11 Oct: up to MAX_CHECKPOINTS checkpoints, visited in the order given.

    `via` is one (lat, lng) or a list of them; `via_label` one label or a list.

    The first variant may go over some of the same ground if no wholly
    different way back exists - a single bridge or gate can force that - and
    says so; the parent's retracing preference then decides, in the open,
    whether it is shown. Later variants are only kept if they are real
    alternatives. Every variant kept passes within reach of every checkpoint
    (or, where the provider moved one further than that, within
    CHECKPOINT_ON_ROUTE_M of where it moved it to). Each Route's `vias`
    records, per checkpoint, that point, the parent's own marker and the
    distance between them; `via` is the last of them.

    With `reach_m` above CHECKPOINT_ON_ROUTE_M the walk need only come that
    close. At the last checkpoint the way out is cut where it first does, and
    the way back starts there. At a checkpoint in between, the walk is routed
    through it, then the stretch inside that distance is replaced by the
    direct path between where the walk enters and leaves it, when that is
    shorter - one extra call per checkpoint.

    Raises CheckpointProblem when a checkpoint is the problem (too close, too
    far for the time, no usable way near it, no route to it).
    """
    key = api_key()
    if not key:
        raise GenerationUnavailable("Walk generation is not configured on this deployment.")
    pins = [tuple(via)] if isinstance(via[0], (int, float)) else [tuple(p) for p in via]
    pins = pins[:MAX_CHECKPOINTS]
    labels = [via_label] if isinstance(via_label, str) else list(via_label)
    labels = [(labels[i] if i < len(labels) and labels[i] else f"checkpoint {i + 1}")
              for i in range(len(pins))]
    many = len(pins) > 1
    via, via_label = pins[-1], labels[-1]            # the turning point
    reach_m = min(max(float(reach_m), CHECKPOINT_ON_ROUTE_M), CHECKPOINT_REACH_MAX_M)
    passing = reach_m > CHECKPOINT_ON_ROUTE_M
    search_m = max(CHECKPOINT_SEARCH_M, int(reach_m))
    check_checkpoints(start, pins, minutes, labels, reach_m)
    character, pram_note = pram_character(profile, character)
    forms = _weight_forms(character)

    def make_base(form):
        p, b = request_body(start, profile, 30, 1, character, form)
        b["options"].pop("round_trip", None)
        return p, b

    def body(base, points, radii, avoid=None):
        # Every leg keeps the profile's own options - steps avoided for a pram -
        # so each is held to the same access rules.
        req = {**base, "coordinates": [[p[1], p[0]] for p in points], "radiuses": radii,
               "options": dict(base["options"])}
        if avoid:
            req["options"]["avoid_polygons"] = avoid
        return req

    def out_body(base, avoid=None):
        return body(base, [start, *pins], [START_SEARCH_M] + [search_m] * len(pins), avoid)

    def back_body(base, at, avoid=None):
        return body(base, [at, start], [search_m, START_SEARCH_M], avoid)

    own = client is None
    client = client or httpx.AsyncClient(timeout=20.0)
    found: List[Tuple[Dict, Optional[str], Tuple[float, float], List[Tuple[float, float]]]] = []
    used: List[Dict] = []        # corridors of every line found so far
    dropped = 0

    async def post(ors_profile, req):
        _spend()
        return await _post(client, ors_profile, req)

    def feature(resp):
        if resp.status_code == 200 and resp.json().get("features"):
            return resp.json()["features"][0]
        return None

    try:
        # The way out for the first variant, learning which weighting form works.
        for form in forms:
            ors_profile, base = make_base(form)
            url = ors_profile
            r1 = await post(url, out_body(base))
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
            if code == 2010 and point is not None and 1 <= point <= len(pins):
                raise CheckpointProblem(
                    "unreachable", f"There's no mapped way suitable for {what} "
                    f"within {search_m} m of {labels[point - 1]}. Move the "
                    "checkpoint onto or near a path.")
            if code == 2010 and point == 0:
                raise GenerationUnavailable(
                    "There's no mapped path near your start. Choose a start on "
                    "or near a path.")
            if code == 2009:
                where = (f"one of your checkpoints ({chain_name(labels)})" if many
                         else via_label)
                raise CheckpointProblem(
                    "no_route", f"No route suitable for {what} reaches {where} "
                    "from your start. It may be on private land, across water, "
                    "or reachable only by steps. Try a different point.")
            raise GenerationUnavailable(
                f"Couldn't find a walking route to {chain_name(labels)}.")

        async def shape(out):
            """The way out, shaped for reach, and the point to turn at.

            The last checkpoint: cut where the way out first comes within
            reach. Each one in between (last first, so earlier indices hold):
            replace the stretch within reach by the direct path between where
            the walk enters and leaves it, when that is shorter."""
            idx = pin_indices(out, pins)
            cs = out["geometry"]["coordinates"]
            if passing:
                from_i = idx[-2] if many else 0
                hit = approach(cs[from_i:], via, reach_m)
                if hit and from_i + hit[0] + 1 < len(cs):
                    out = cut_feature(out, from_i + hit[0], hit[1])
            if passing and many:
                for k in range(len(pins) - 2, -1, -1):
                    cs = out["geometry"]["coordinates"]
                    idx = pin_indices(out, pins[:k + 1]) + idx[k + 1:]
                    lo = idx[k - 1] if k else 0
                    hi = idx[k + 1] if k + 1 < len(idx) else len(cs) - 1
                    near = [i for i in range(lo, min(hi, len(cs) - 1) + 1)
                            if _haversine((cs[i][1], cs[i][0]), pins[k]) <= reach_m]
                    if len(near) < 2:
                        continue
                    a, b = near[0], near[-1]
                    pa, pb = (cs[a][1], cs[a][0]), (cs[b][1], cs[b][0])
                    along = sum(_haversine((cs[i][1], cs[i][0]), (cs[i + 1][1], cs[i + 1][0]))
                                for i in range(a, b))
                    if b - a < 2 or along <= _haversine(pa, pb) + 30:
                        continue
                    short = feature(await post(url, body(base, [pa, pb], [40, 40])))
                    if short and short.get("properties", {}).get("summary", {}).get(
                            "distance", along) < along - 10:
                        out = splice(out, a, b, short)
            end = out["geometry"]["coordinates"][-1]
            return out, (end[1], end[0])

        def routed_points(line_feat, at):
            """Per checkpoint, the point of the walk that serves it: where it
            turns, for the last; the walk's closest point, for the others."""
            cs = line_feat["geometry"]["coordinates"]
            pts = []
            for p in pins[:-1]:
                i = min(range(len(cs)), key=lambda j: _haversine((cs[j][1], cs[j][0]), p))
                pts.append((cs[i][1], cs[i][0]))
            return pts + [at]

        # Where the walk really turns: where the provider took the way out,
        # or where it first came close enough.
        first_out, routed = await shape(first_out)
        first_points = routed_points(first_out, routed)
        close = [_haversine(p, q) <= reach_m + 1.0 for p, q in zip(pins, first_points)]
        close_enough = all(close)
        holes = list(pins) + first_points

        for k in range(VIA_VARIANTS):
            if k == 0:
                out, at = first_out, routed
            else:
                out = feature(await post(url, out_body(base, _merge(*used))))
                if out is None:
                    break
                out, at = await shape(out)
            out_line = corridor(out["geometry"]["coordinates"])
            back = feature(await post(url, back_body(base, at, _merge(out_line, *used))))
            if back is None and used:
                back = feature(await post(url, back_body(base, at, out_line)))
            note = None
            if back is None and k == 0:
                back = feature(await post(url, back_body(base, at)))
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
            # Kept only if it really comes close enough to every checkpoint:
            # within the parent's reach of their marker, or - where even the
            # first walk could not, and the parent must accept a moved point -
            # within 25 m of where the provider moved it.
            missed = any(
                closest_m(line, p) > reach_m + 1.0 if ok
                else closest_m(line, q) > CHECKPOINT_ON_ROUTE_M
                for p, q, ok in zip(pins, first_points, close))
            if missed:
                dropped += 1
                continue
            if any(_overlap(line, j["geometry"]["coordinates"]) > DUPLICATE_SHARE
                   for j, _, _, _ in found):
                break
            found.append((joined, note, at, routed_points(out, at)))
            # Later walks avoid these paths, except round every checkpoint,
            # which they must still reach.
            used += [c for c in (corridor(out["geometry"]["coordinates"], holes),
                                 corridor(back["geometry"]["coordinates"], holes)) if c]
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
    for n, (joined, note, at, points) in enumerate(found, start=1):
        if pram_note:
            note = f"{note} {pram_note}" if note else pram_note
        if passing and close_enough:
            pass_note = (f"Turns back about {round(_haversine(via, at))} m from "
                         f"{via_label}, as close as you asked it to come.")
            if many:
                pass_note += (" It passes the other checkpoints within "
                              f"{round(reach_m)} m too.")
            note = f"{note} {pass_note}" if note else pass_note
        r = route_from_ors(joined, walk_id=f"via-{n}",
                           name=f"Via {chain_name(labels)}" + (f", option {n}" if n > 1 else ""),
                           start_label=start_label, routing_note=note)
        r.vias = [{"lat": q[0], "lng": q[1], "label": lab,
                   "requested": {"lat": p[0], "lng": p[1]},
                   "offset_m": round(_haversine(p, q)), "reach_m": round(reach_m)}
                  for p, q, lab in zip(pins, points, labels)]
        r.via = r.vias[-1]
        routes.append(r)
    return routes


# ------------------------------------------------------------ your own route
#
# Founder request, 11 Oct 2026: walks Driftway makes are not always the ones
# a parent actually walks - his own Long Walk loop never came up. A route of
# their own (drawn on the map, imported from a GPX file, or a made walk they
# saved) arrives as points in the order walked. It is routed through them
# along mapped ways with the profile's own rules, then judged like any other
# walk. The points are kept on the parent's device, not here.

#: Most points one route may pass. openrouteservice takes up to 50 waypoints
#: per request on the standard plan; a margin is kept.
MAX_TRACE_POINTS = 40
#: How far a tapped or imported point may be from a usable way.
TRACE_SNAP_M = 100
#: A route whose end is this close to its start is a loop.
TRACE_LOOP_M = 150.0


class TraceProblem(GenerationUnavailable):
    """One of the parent's points is the problem; `point` is its number
    (1-based), when known."""

    def __init__(self, message: str, point: Optional[int] = None):
        super().__init__(message)
        self.point = point


async def trace_walk(points: List[Tuple[float, float]], profile: str, name: str,
                     start_label: str,
                     client: Optional[httpx.AsyncClient] = None) -> Route:
    """The parent's own route through `points`, in order, along mapped ways
    suitable for `profile`. One provider call. Raises TraceProblem when a
    point is the problem, GenerationUnavailable otherwise."""
    if not api_key():
        raise GenerationUnavailable("Walk generation is not configured on this deployment.")
    pts = [tuple(p) for p in points][:MAX_TRACE_POINTS]
    if len(pts) < 2:
        raise TraceProblem("A route needs at least two points.")
    # The profile's own options, steps avoided for a pram: a route of your
    # own is held to the same access rules as any other walk.
    ors_profile, req = request_body(pts[0], profile, 30, 1, "any", None)
    req["options"].pop("round_trip", None)
    req["coordinates"] = [[p[1], p[0]] for p in pts]
    req["radiuses"] = [TRACE_SNAP_M] * len(pts)

    own = client is None
    client = client or httpx.AsyncClient(timeout=20.0)
    try:
        _spend()
        resp = await _post(client, ors_profile, req)
    finally:
        if own:
            await client.aclose()

    no = refused(resp)
    if no:
        log.warning("openrouteservice %s for a route of your own - %s",
                    resp.status_code, _ors_error(resp))
        raise no
    features = resp.json().get("features") if resp.status_code == 200 else None
    if not features:
        log.warning("openrouteservice %s for a route of your own - %s",
                    resp.status_code, _ors_error(resp))
        code, point = _ors_failure(resp)
        what = {"pram": "a pram", "carrier": "walking with a carrier",
                "walker": "walking"}.get(profile, "walking")
        if code == 2010 and point is not None and 0 <= point < len(pts):
            raise TraceProblem(
                f"Point {point + 1} of your route isn't within {TRACE_SNAP_M} m of a "
                f"mapped way suitable for {what}. Move it onto or near a path.",
                point + 1)
        if code == 2009:
            raise TraceProblem(
                f"There's no mapped way suitable for {what} between some of your "
                "points. Part of the route may be private, across water, or only "
                "reachable by steps.")
        raise GenerationUnavailable("Couldn't follow your route just now.")

    route = route_from_ors(features[0], walk_id="mine", name=name or "Your route",
                           start_label=start_label)
    closed = _haversine(pts[0], pts[-1]) <= TRACE_LOOP_M
    route.shape = "loop" if closed else "out_and_back"
    route.summary = ("Your own route, along mapped paths." if closed else
                     "Your own route, along mapped paths. It ends away from its "
                     "start, so it is walked there and back.")
    route.notes = [
        "Follows mapped paths through your points. Between two points it takes "
        "the shortest suitable way, which may not be the one you walk: more "
        "points keep it closer.",
    ] + [n for n in route.notes if not n.startswith("Generated just now")]
    if profile == "pram":
        route.notes.append("Where your way isn't suitable for a pram, this goes "
                           "another way. Check it on the map.")
    return route

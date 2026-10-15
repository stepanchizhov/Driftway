"""
Validation and scoring.

Validation rejects loops that would be unpleasant or absurd (early pass near
home, heavy self-overlap, etc.). Scoring ranks the survivors. All weights are
HYPOTHESES from the project bible; real ride data should retune them.
"""

from __future__ import annotations

import json
import math
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Dict, Iterator, List, Optional, Tuple

from .geometry import haversine_km, initial_bearing
from .models import Coord, RoadMix
from .router import EvaluatedRoute
from . import calming
from . import roadworks


# ---------------------------------------------------------------- validation

def _self_overlap_ratio(geometry: List[Coord]) -> float:
    """Crude self-overlap estimate: fraction of points that are very close to
    a non-adjacent earlier point. Cheap proxy for "the route doubles back on
    itself". Good enough to filter the worst offenders for the alpha."""
    if len(geometry) < 8:
        return 0.0
    near = 0
    step = max(1, len(geometry) // 60)          # subsample for speed
    pts = geometry[::step]
    for i in range(len(pts)):
        for j in range(i + 3, len(pts)):        # skip immediate neighbours
            if haversine_km(pts[i], pts[j]) < 0.15:   # within 150 m
                near += 1
                break
    return near / len(pts)


def _passes_near_finish_early(geometry: List[Coord], finish: Coord) -> bool:
    """Return True when the route passes near the finish too early in the trip.

    This is a heuristic for loops that double back home prematurely. For a loop,
    start and finish are usually the same location, so the route legitimately
    begins and ends near the goal. We therefore inspect only the middle band
    (20%-80% of the route) and ignore the departure/arrival legs.
    """
    n = len(geometry)
    if n < 12:
        return False
    # A short loop never gets far from home, so "passes within 300 m of the
    # finish" is what it looks like when it is working, not a fault. Without
    # this exemption every 5-10 minute loop is rejected on principle.
    reach_km = max(haversine_km(pt, finish) for pt in geometry)
    if reach_km < 2.0:
        return False
    lo = int(n * 0.20)   # skip the departure away from Home
    hi = int(n * 0.80)   # skip the final approach back to Home
    for pt in geometry[lo:hi]:
        if haversine_km(pt, finish) < 0.3:
            return True
    return False


# How sharply the route has to double back at a waypoint before we call it a
# turn-around rather than a bend. 150 degrees is well past any real junction.
TURNAROUND_ANGLE_DEG = 150.0
# How far either side of the waypoint to measure the approach and departure.
# Short enough to ignore the wider shape of the loop, long enough to survive
# the clustered points TomTom emits around a junction.
TURNAROUND_WINDOW_KM = 0.2


def _walk_from(geometry: List[Coord], idx: int, step: int,
               distance_km: float) -> Optional[Coord]:
    """Follow the path from geometry[idx] until `distance_km` has been covered.

    `step` is +1 to walk forwards, -1 to walk back. Returns None when the path
    ends first, which means there is not enough road either side to judge.
    """
    travelled = 0.0
    i = idx
    while 0 <= i + step < len(geometry):
        travelled += haversine_km(geometry[i], geometry[i + step])
        i += step
        if travelled >= distance_km:
            return geometry[i]
    return None


def _nearest_index(geometry: List[Coord], point: Coord) -> int:
    return min(range(len(geometry)),
               key=lambda i: haversine_km(geometry[i], point))


def turnaround_waypoints(route: EvaluatedRoute) -> int:
    """Count waypoints the route has to double back at."""
    return len(turnaround_points(route))


def turnaround_points(route: EvaluatedRoute) -> List[Coord]:
    """Where the route doubles back at a waypoint."""
    return [p for _i, p in turnaround_anchors(route)]


def turnaround_anchors(route: EvaluatedRoute) -> List[Tuple[int, Coord]]:
    """(waypoint index, where on the route) for each waypoint the route
    doubles back at.

    This is the three-point-turn / dead-end-spur detector. The global overlap
    ratio cannot see these: a 200 m spur off a 12 km loop is a rounding error
    by that measure, but it is the part of the drive that wakes the baby.

    Works on the returned polyline, so it costs nothing extra.
    """
    geometry = route.geometry
    if len(geometry) < 6 or not route.anchors:
        return []
    points: List[Tuple[int, Coord]] = []
    for n, anchor in enumerate(route.anchors):
        idx = _nearest_index(geometry, anchor)
        before = _walk_from(geometry, idx, -1, TURNAROUND_WINDOW_KM)
        after = _walk_from(geometry, idx, +1, TURNAROUND_WINDOW_KM)
        if before is None or after is None:
            continue
        arriving = initial_bearing(before, geometry[idx])
        leaving = initial_bearing(geometry[idx], after)
        turn = abs(((leaving - arriving + 180) % 360) - 180)
        if turn >= TURNAROUND_ANGLE_DEG:
            points.append((n, geometry[idx]))
    return points


# A turn-around at an easy place to turn (a roundabout, a turning circle, a
# loop round an island: calming.easy_turn_at) counts this much of one that
# needs a three-point turn. Founder, 13 Oct 2026, from a drive whose spike
# ended at a loop round a small island: easy places are better. HYPOTHESIS
# weight.
EASY_TURN_WEIGHT = 0.3


def easy_turns(route: EvaluatedRoute) -> List[str]:
    """The kinds of easy place the route turns round at, one per turn-around
    that is at one (the rest need a three-point turn or a U-turn)."""
    pts = list(route.uturn_points) + turnaround_points(route)
    return [k for k in (calming.easy_turn_at(p.lat, p.lng) for p in pts) if k]


def turn_load(route: EvaluatedRoute) -> float:
    """Turn-arounds, an easy one counting EASY_TURN_WEIGHT."""
    n = turnaround_count(route)
    if n == 0:
        return 0.0
    return max(0.0, n - (1.0 - EASY_TURN_WEIGHT) * min(n, len(easy_turns(route))))


def turnaround_count(route: EvaluatedRoute) -> int:
    """Total turn-arounds on this route, from both detectors.

    NOT part of validation, deliberately. Measured against TomTom, every single
    generated loop contained at least one - 24 out of 24 across dense, suburban
    and rural starts. Rejecting on it would reject everything, so it ranks
    routes instead of filtering them. See the note in generator.py about why
    hard waypoints cause this. Since asking TomTom to avoid roads already used
    (10 Oct 2026), 5 of 11 measured loops had none - still not enough to
    filter on.
    """
    return (1 if route.has_uturn else 0) + turnaround_waypoints(route)


def rejection_reason(route: EvaluatedRoute, finish: Coord) -> Optional[str]:
    """Return why a route is invalid, or None if it passes. Used for logging
    so empty results are diagnosable from the Render logs."""
    if route.minutes <= 0 or route.distance_km <= 0:
        return "no_duration"
    if _self_overlap_ratio(route.geometry) > 0.35:
        return "overlap"
    if _passes_near_finish_early(route.geometry, finish):
        return "early_finish"
    return None


def passes_validation(route: EvaluatedRoute, finish: Coord) -> bool:
    return rejection_reason(route, finish) is None


# ------------------------------------------------------------------- scoring

def _road_mix_match(mix: RoadMix, profile: str) -> float:
    """1.0 = perfect match to the requested profile, 0.0 = opposite."""
    major = mix.motorway + mix.primary
    quiet = mix.secondary + mix.residential
    if profile == "motorway":
        return major
    if profile == "quiet":
        return quiet
    # mixed: best when neither extreme dominates
    return 1.0 - abs(major - quiet)


# Weights from the project bible (illustrative; tune from ride data).
# Duration dominates: the whole promise of the app is "about N minutes", so a
# prettier loop of the wrong length must never outrank a plainer one that
# lands on time. Smoothness is second because a three-point turn is the thing
# most likely to wake the baby, which is the only failure that really counts.
W_DURATION = 0.50
W_SMOOTH = 0.20
W_LOOP = 0.20
W_PROFILE = 0.10

# Each turn-around costs half the smoothness score, so one is a real penalty
# and two is close to total.
TURNAROUND_COST = 0.5


# Mapped speed bumps (docs/CALMER_DRIVES.md, 11 Oct 2026). HYPOTHESIS
# weights, tuned offline on 160 real candidates around Windsor: a drive with
# a mapped bump every kilometre or more loses a quarter of a point. Bumps
# never buy a worse drive on what already counted - see calmer_lead below -
# so this only decides between drives that are otherwise as good.
W_BUMPS = 0.25
BUMPS_PER_KM_FULL = 1.0
# A drive with no count (outside the prepared data) scores like a typical
# drive (about 0.7 per km in the measurement): missing data is neither
# rewarded nor punished.
UNKNOWN_BUMP_SCORE = 1.0 - 0.7 / BUMPS_PER_KM_FULL


def bumps_of(route: EvaluatedRoute):
    """The route's mapped speed bumps (calming.BumpCount), or None outside
    the prepared data. Counted once per route."""
    if not route.bumps_checked:
        route.bumps = calming.count_along(route.geometry)
        route.bumps_checked = True
    return route.bumps


# Traffic lights (founder, 12 Oct 2026: a stop at lights may wake a baby
# more than a bump). HYPOTHESIS weights: a drive meeting lights once a
# kilometre or more (a junction or a pedestrian crossing) loses W_LIGHTS.
# Measured on 160 real candidates around Windsor: a median drive meets about
# 11, and one start's candidates ranged from 3 to 29 junctions.
W_LIGHTS = 0.3
LIGHTS_PER_KM_FULL = 1.0
UNKNOWN_LIGHT_SCORE = 1.0 - 0.55 / LIGHTS_PER_KM_FULL


def lights_of(route: EvaluatedRoute):
    """The route's traffic lights (calming.LightCount), or None outside the
    prepared data. Counted once per route."""
    if not route.lights_checked:
        route.lights = calming.lights_along(route.geometry)
        route.lights_checked = True
    return route.lights


def _light_score(route: EvaluatedRoute) -> float:
    """1.0 = no lights mapped, 0.0 = LIGHTS_PER_KM_FULL or more per km."""
    lights = lights_of(route)
    if lights is None:
        return UNKNOWN_LIGHT_SCORE
    return 1.0 - min(1.0, lights.per_km / LIGHTS_PER_KM_FULL)


# Roadworks that stop traffic (Street Manager; founder, 12 Oct 2026: a
# stop-go may be the worst thing for a sleeping baby). HYPOTHESIS: one such
# work costs as much as a drive full of lights. Still under the guard.
W_WORKS = 0.5
#: A TomTom roadworks of unknown control counts this share of one that stops
#: traffic: most roadworks narrow a lane without stopping anyone.
UNKNOWN_WORKS_SHARE = 0.25


def works_of(route: EvaluatedRoute) -> list:
    if route.works is None:
        route.works = roadworks.works_for(route.geometry)
    return route.works


def _works_score(route: EvaluatedRoute) -> float:
    works = works_of(route)
    stopping = sum(1 for w in works if w.control in roadworks.STOPPING)
    # TomTom roadworks that don't say how traffic is controlled
    # (core/incidents.py): some stop it, most don't.
    unknown = sum(1 for w in works if w.control == "roadworks")
    return 1.0 - min(1.0, stopping + UNKNOWN_WORKS_SHARE * unknown)


def _bump_score(route: EvaluatedRoute) -> float:
    """1.0 = no mapped bumps, 0.0 = BUMPS_PER_KM_FULL or more per km."""
    b = bumps_of(route)
    if b is None:
        return UNKNOWN_BUMP_SCORE
    return 1.0 - min(1.0, b.per_km / BUMPS_PER_KM_FULL)


def _smoothness(route: EvaluatedRoute) -> float:
    """1.0 = never asks the driver to double back."""
    return max(0.0, 1.0 - TURNAROUND_COST * turn_load(route) * feeling("turns"))


def score_route(route: EvaluatedRoute, target_minutes: int, profile: str,
                with_bumps: bool = True) -> float:
    duration_score = max(0.0, 1.0 - abs(route.minutes - target_minutes) / target_minutes)
    loop_score = 1.0 - min(1.0, _self_overlap_ratio(route.geometry))
    profile_score = _road_mix_match(route.road_mix, profile)
    return round(
        W_DURATION * duration_score
        + W_SMOOTH * _smoothness(route)
        + W_LOOP * loop_score
        + W_PROFILE * profile_score
        + (W_BUMPS * _bump_score(route) + W_LIGHTS * _light_score(route)
           + W_WORKS * _works_score(route) if with_bumps else 0.0),
        4,
    )


#: EXPERIMENT (founder and Astra brief, 15 Oct 2026): the first drive offered
#: lands at most this many minutes further from the time asked for than the
#: closest-to-time eligible candidate, whatever ranked it first: fewer stops
#: (calmer_lead), fewer or easier turn-arounds (the smoothness score), or a
#: waypoint moved to an easy place to turn. Compared on each candidate's
#: final routed duration. Measured 13 Oct before this: moving turn-backs put
#: three first drives 4 to 8 minutes further off. Two minutes is a starting
#: point, not an established optimum; revise it here. It never widens the
#: request's own tolerance window, which still decides who is eligible.
FIRST_EXTRA_MIN = 2.0

# Stops as a parent meets them, on one scale (founder, 13 Oct 2026: "a
# turn-around is better than a red light, and especially better than a
# stop-go"). A bump and a turn-around count 1, lights 1.2, roadworks that
# stop traffic 4. Counted per drive, not per km: a longer drive with more
# lights is not calmer.
STOP_WEIGHT = {"bump": 1.0, "junction": 1.2, "pedestrian": 1.0, "works": 4.0,
               # Roadworks whose traffic control isn't known (TomTom).
               "roadworks": 1.0}
TURN_WEIGHT = 1.0
#: A drive must spare at least this much (two bumps) to go first for it.
CALM_GAIN = 2.0

# What wakes this child (founder, 13 Oct 2026: it "can be different for each
# child"). The parent's answer per kind of stop scales its weight above, in
# the choice of the first drive, in steering round busy stretches, and for
# turn-arounds also in the smoothness every drive is ranked by. HYPOTHESIS
# factors: "doesn't bother them" keeps a quarter, "wakes them" counts two
# and a half times.
FEELING_FACTOR = {"fine": 0.25, "sometimes": 1.0, "wakes": 2.5}
#: Which answer each weight follows.
_FEELING_OF = {"bump": "bumps", "junction": "lights", "pedestrian": "lights",
               "works": "works", "roadworks": "works"}
_feelings: ContextVar[Dict[str, float]] = ContextVar("stop_feelings", default={})


@contextmanager
def stop_preferences(prefs) -> Iterator[None]:
    """For one drive request: the parent's answers (models.StopPrefs, or
    None for the usual weights)."""
    factors = {} if prefs is None else {
        k: FEELING_FACTOR[getattr(prefs, k).value] for k in ("bumps", "lights", "turns", "works")}
    token = _feelings.set(factors)
    try:
        yield
    finally:
        _feelings.reset(token)


def feeling(group: str) -> float:
    return _feelings.get().get(group, 1.0)


def weight(kind: str) -> float:
    """A stop's weight on the scale, for this child."""
    return STOP_WEIGHT[kind] * feeling(_FEELING_OF[kind])


def stops_on(route: EvaluatedRoute) -> List[Tuple[float, float, float, float]]:
    """(metres along, lat, lng, weight) for every mapped stop on the drive:
    bumps, lights (core.calming) and roadworks that stop traffic."""
    out = [(s, lat, lng, weight(kind))
           for s, lat, lng, kind in calming.stops_along(route.geometry)]
    pts = [(p.lat, p.lng) for p in route.geometry]
    if len(pts) < 2:
        return out
    k = math.cos(math.radians(pts[0][0]))
    cum = None
    for w in works_of(route):
        if w.control not in roadworks.STOPPING:
            continue
        wp = json.loads(w.points_json or "[]")
        if not wp:
            continue
        lat, lng = sum(p[0] for p in wp) / len(wp), sum(p[1] for p in wp) / len(wp)
        if cum is None:
            cum = [0.0]
            for a, b in zip(pts, pts[1:]):
                cum.append(cum[-1] + math.hypot((b[0] - a[0]) * 111320.0, (b[1] - a[1]) * 111320.0 * k))
        i = min(range(len(pts)), key=lambda j: (pts[j][0] - lat) ** 2 + ((pts[j][1] - lng) * k) ** 2)
        out.append((cum[i], lat, lng, weight("works")))
    return sorted(out)


def stop_weight(route: EvaluatedRoute) -> float:
    """The drive's mapped stops, weighted (STOP_WEIGHT), from the counts the
    card shows: 0 outside the prepared data."""
    b, lights = bumps_of(route), lights_of(route)
    works = works_of(route)
    stopping = sum(1 for w in works if w.control in roadworks.STOPPING)
    unknown = sum(1 for w in works if w.control == "roadworks")
    return (unknown * weight("roadworks")
            + (b.count if b else 0) * weight("bump")
            + (lights.junctions * weight("junction") + lights.pedestrian * weight("pedestrian")
               if lights else 0.0)
            + stopping * weight("works"))


def stops_met(route: EvaluatedRoute) -> float:
    """Everything that stops or turns the car round, on one scale."""
    return stop_weight(route) + TURN_WEIGHT * feeling("turns") * turn_load(route)


def calmer_lead(ranked: List[EvaluatedRoute], target_minutes: int,
                profile: str) -> List[EvaluatedRoute]:
    """Put a calmer drive first, if one is as good on what already counted.

    `ranked` is in the order the score without bumps gives. A candidate
    within FIRST_EXTRA_MIN of the closest-to-time candidate may replace the
    first drive if a parent meets fewer stops on it (stops_met, by at least
    CALM_GAIN), turn-arounds counted like a bump. Only the first place
    changes. first_within_time then bounds whatever is first.

    Until 13 Oct 2026 a calmer drive could never add a turn-around, which
    made a turn-around worth about seven sets of lights. The founder, who
    drives these with a sleeping baby: a turn-around is better than a red
    light. Measured that day on 20 Windsor requests: the first drive changes
    in 7; across all 20, bumps 222 to 167, lights 157 to 141, turn-arounds 14
    to 22, timing no worse (82 to 78 minutes off in total).
    """
    if not ranked:
        return ranked
    lead = ranked[0]
    limit = min(abs(ev.minutes - target_minutes) for ev in ranked) + FIRST_EXTRA_MIN + 1e-9
    eligible = [ev for ev in ranked if abs(ev.minutes - target_minutes) <= limit]
    if not eligible:
        return ranked
    best = min(eligible, key=stops_met)
    if best is lead or (lead in eligible and stops_met(best) > stops_met(lead) - CALM_GAIN):
        return ranked
    return [best] + [ev for ev in ranked if ev is not best]


def first_within_time(ranked: List[EvaluatedRoute], target_minutes: int) -> List[EvaluatedRoute]:
    """The ranking, with the first drive within FIRST_EXTRA_MIN of the
    closest-to-time candidate: if the leader is further off, the best-ranked
    candidate within it goes first instead, and the leader stays in the list
    (as an alternative whose card says what it trades)."""
    if not ranked:
        return ranked
    limit = min(abs(ev.minutes - target_minutes) for ev in ranked) + FIRST_EXTRA_MIN + 1e-9
    if abs(ranked[0].minutes - target_minutes) <= limit:
        return ranked
    first = next(ev for ev in ranked if abs(ev.minutes - target_minutes) <= limit)
    return [first] + [ev for ev in ranked if ev is not first]


def tradeoff_note(ev: EvaluatedRoute, lead: EvaluatedRoute, target_minutes: int) -> Optional[str]:
    """For an alternative a parent meets materially fewer stops on than the
    first drive: what it gains and gives up, kind by kind, so a lower total
    cannot hide more of one kind, and how much further from the time it is."""
    if ev is lead or stops_met(ev) > stops_met(lead) - CALM_GAIN:
        return None

    def counts(r):
        b, lt = bumps_of(r), lights_of(r)
        works = works_of(r)
        return {"speed bump": b.count if b else None,
                "set of lights": lt.total if lt else None,
                "turn-around": turnaround_count(r),
                "roadworks": sum(1 for w in works if w.control in roadworks.STOPPING or w.control == "roadworks")}

    plural = {"speed bump": "speed bumps", "set of lights": "sets of lights",
              "turn-around": "turn-arounds", "roadworks": "roadworks"}
    mine, theirs = counts(ev), counts(lead)
    parts = []
    for kind in mine:
        a, b = mine[kind], theirs[kind]
        if a is None or b is None or a == b:
            continue
        n = abs(a - b)
        word = kind if n == 1 else plural[kind]
        parts.append(f"{n} {'fewer' if a < b else 'more'} {word}")
    off = abs(ev.minutes - target_minutes) - abs(lead.minutes - target_minutes)
    when = (f", about {round(off)} min further from your {target_minutes} min" if off >= 1
            else "")
    return "Calmer than the first drive: " + (", ".join(parts) or "fewer stops") + when + "."


def describe_character(mix: RoadMix) -> str:
    """Human-readable summary for the route card."""
    major = mix.motorway + mix.primary
    if mix.motorway >= 0.4:
        return "Mostly motorway and major roads"
    if major >= 0.55:
        return "Mostly A-roads with some local stretches"
    if mix.residential + mix.secondary >= 0.7:
        return "Quieter local and B-roads"
    return "Mixed suburban and rural roads"


def dedupe(routes: List[EvaluatedRoute], min_distance_diff_km: float = 1.5) -> List[EvaluatedRoute]:
    """Drop near-identical routes so the three options are meaningfully
    different. Keeps the first (higher-scored) of any close pair."""
    kept: List[EvaluatedRoute] = []
    for r in routes:
        if all(abs(r.distance_km - k.distance_km) > min_distance_diff_km
               or _anchor_distance(r, k) > 2.0 for k in kept):
            kept.append(r)
    return kept


def _anchor_distance(a: EvaluatedRoute, b: EvaluatedRoute) -> float:
    """Mean distance between the first anchors of two routes (rough diversity
    measure)."""
    if not a.anchors or not b.anchors:
        return 99.0
    return haversine_km(a.anchors[0], b.anchors[0])

"""
Validation and scoring.

Validation rejects loops that would be unpleasant or absurd (early pass near
home, heavy self-overlap, etc.). Scoring ranks the survivors. All weights are
HYPOTHESES from the project bible; real ride data should retune them.
"""

from __future__ import annotations

import json
import math
from typing import List, Optional, Tuple

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
    """Count waypoints the route has to double back at.

    This is the three-point-turn / dead-end-spur detector. The global overlap
    ratio cannot see these: a 200 m spur off a 12 km loop is a rounding error
    by that measure, but it is the part of the drive that wakes the baby.

    Works on the returned polyline, so it costs nothing extra.
    """
    geometry = route.geometry
    if len(geometry) < 6 or not route.anchors:
        return 0
    count = 0
    for anchor in route.anchors:
        idx = _nearest_index(geometry, anchor)
        before = _walk_from(geometry, idx, -1, TURNAROUND_WINDOW_KM)
        after = _walk_from(geometry, idx, +1, TURNAROUND_WINDOW_KM)
        if before is None or after is None:
            continue
        arriving = initial_bearing(before, geometry[idx])
        leaving = initial_bearing(geometry[idx], after)
        turn = abs(((leaving - arriving + 180) % 360) - 180)
        if turn >= TURNAROUND_ANGLE_DEG:
            count += 1
    return count


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


def works_of(route: EvaluatedRoute) -> list:
    if route.works is None:
        route.works = roadworks.works_for(route.geometry)
    return route.works


def _works_score(route: EvaluatedRoute) -> float:
    stopping = sum(1 for w in works_of(route) if w.control in roadworks.STOPPING)
    return 1.0 - min(1.0, float(stopping))


def _bump_score(route: EvaluatedRoute) -> float:
    """1.0 = no mapped bumps, 0.0 = BUMPS_PER_KM_FULL or more per km."""
    b = bumps_of(route)
    if b is None:
        return UNKNOWN_BUMP_SCORE
    return 1.0 - min(1.0, b.per_km / BUMPS_PER_KM_FULL)


def _smoothness(route: EvaluatedRoute) -> float:
    """1.0 = never asks the driver to double back."""
    return max(0.0, 1.0 - TURNAROUND_COST * turnaround_count(route))


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


#: A calmer drive may land this many minutes further from the time asked
#: for than the drive it replaces, and no more.
CALM_SLACK_MIN = 3.0

# Stops as a parent meets them, on one scale (founder, 13 Oct 2026: "a
# turn-around is better than a red light, and especially better than a
# stop-go"). A bump and a turn-around count 1, lights 1.2, roadworks that
# stop traffic 4. Counted per drive, not per km: a longer drive with more
# lights is not calmer.
STOP_WEIGHT = {"bump": 1.0, "junction": 1.2, "pedestrian": 1.0, "works": 4.0}
TURN_WEIGHT = 1.0
#: A drive must spare at least this much (two bumps) to go first for it.
CALM_GAIN = 2.0


def stops_on(route: EvaluatedRoute) -> List[Tuple[float, float, float, float]]:
    """(metres along, lat, lng, weight) for every mapped stop on the drive:
    bumps, lights (core.calming) and roadworks that stop traffic."""
    out = [(s, lat, lng, STOP_WEIGHT[kind])
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
        out.append((cum[i], lat, lng, STOP_WEIGHT["works"]))
    return sorted(out)


def stop_weight(route: EvaluatedRoute) -> float:
    """The drive's mapped stops, weighted (STOP_WEIGHT), from the counts the
    card shows: 0 outside the prepared data."""
    b, lights = bumps_of(route), lights_of(route)
    stopping = sum(1 for w in works_of(route) if w.control in roadworks.STOPPING)
    return ((b.count if b else 0) * STOP_WEIGHT["bump"]
            + (lights.junctions * STOP_WEIGHT["junction"] + lights.pedestrian * STOP_WEIGHT["pedestrian"]
               if lights else 0.0)
            + stopping * STOP_WEIGHT["works"])


def stops_met(route: EvaluatedRoute) -> float:
    """Everything that stops or turns the car round, on one scale."""
    return stop_weight(route) + TURN_WEIGHT * turnaround_count(route)


def calmer_lead(ranked: List[EvaluatedRoute], target_minutes: int,
                profile: str) -> List[EvaluatedRoute]:
    """Put a calmer drive first, if one is as good on what already counted.

    `ranked` is in the order the score without bumps gives. A candidate at
    most CALM_SLACK_MIN minutes further from the time may replace the first
    drive if a parent meets fewer stops on it (stops_met, by at least
    CALM_GAIN), turn-arounds counted like a bump. Only the first place
    changes.

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
    lead_miss = abs(lead.minutes - target_minutes)
    eligible = [ev for ev in ranked
                if abs(ev.minutes - target_minutes) <= lead_miss + CALM_SLACK_MIN]
    best = min(eligible, key=stops_met)
    if best is lead or stops_met(best) > stops_met(lead) - CALM_GAIN:
        return ranked
    return [best] + [ev for ev in ranked if ev is not best]


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

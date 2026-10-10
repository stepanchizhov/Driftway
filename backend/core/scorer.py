"""
Validation and scoring.

Validation rejects loops that would be unpleasant or absurd (early pass near
home, heavy self-overlap, etc.). Scoring ranks the survivors. All weights are
HYPOTHESES from the project bible; real ride data should retune them.
"""

from __future__ import annotations

from typing import List, Optional

from .geometry import haversine_km, initial_bearing
from .models import Coord, RoadMix
from .router import EvaluatedRoute


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


def _smoothness(route: EvaluatedRoute) -> float:
    """1.0 = never asks the driver to double back."""
    return max(0.0, 1.0 - TURNAROUND_COST * turnaround_count(route))


def score_route(route: EvaluatedRoute, target_minutes: int, profile: str) -> float:
    duration_score = max(0.0, 1.0 - abs(route.minutes - target_minutes) / target_minutes)
    loop_score = 1.0 - min(1.0, _self_overlap_ratio(route.geometry))
    profile_score = _road_mix_match(route.road_mix, profile)
    return round(
        W_DURATION * duration_score
        + W_SMOOTH * _smoothness(route)
        + W_LOOP * loop_score
        + W_PROFILE * profile_score,
        4,
    )


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

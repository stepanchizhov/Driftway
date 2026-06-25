"""
Validation and scoring.

Validation rejects loops that would be unpleasant or absurd (early pass near
home, heavy self-overlap, etc.). Scoring ranks the survivors. All weights are
HYPOTHESES from the project bible; real ride data should retune them.
"""

from __future__ import annotations

from typing import List, Optional

from .geometry import haversine_km
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
    """True if the route comes within 300 m of the finish before the final
    fifth of the journey — a loop that 'arrives home' too soon."""
def _passes_near_finish_early(geometry: List[Coord], finish: Coord) -> bool:
    """True only if the route passes near the finish in the *middle* of the
    journey — a genuine premature return.

    Important: for a loop, start and finish are usually the same point (Home),
    so the route legitimately begins AND ends near the finish. We must ignore
    those. We only inspect the middle band (20%-80% of the route); a pass near
    the finish there means the loop doubles back home too soon.
    """
    n = len(geometry)
    if n < 12:
        return False
    lo = int(n * 0.20)   # skip the departure away from Home
    hi = int(n * 0.80)   # skip the final approach back to Home
    for pt in geometry[lo:hi]:
        if haversine_km(pt, finish) < 0.3:
            return True
    return False


def rejection_reason(route: EvaluatedRoute, finish: Coord) -> Optional[str]:
    """Return why a route is invalid, or None if it passes. Used for logging
    so empty results are diagnosable from the Render logs."""
    if route.minutes <= 0 or route.distance_km <= 0:
        return "no_duration"
    if route.has_uturn:
        return "uturn"
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
W_DURATION = 0.35
W_LOOP = 0.20
W_PROFILE = 0.15
W_PLACEHOLDER = 0.30   # stop-start + resilience + smoothness + confidence


def score_route(route: EvaluatedRoute, target_minutes: int, profile: str) -> float:
    duration_score = max(0.0, 1.0 - abs(route.minutes - target_minutes) / target_minutes)
    loop_score = 1.0 - min(1.0, _self_overlap_ratio(route.geometry))
    profile_score = _road_mix_match(route.road_mix, profile)
    placeholder = 0.7   # neutral until real smoothness signals exist
    return round(
        W_DURATION * duration_score
        + W_LOOP * loop_score
        + W_PROFILE * profile_score
        + W_PLACEHOLDER * placeholder,
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

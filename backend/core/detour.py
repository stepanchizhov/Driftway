"""
Padded route to a destination.

This is the general case of which a loop is a special instance: given a start,
a finish, and a target duration, produce a route that takes about that long and
ends at the finish. When finish == start you get a loop; when they differ you
get a detour that pads the direct drive (e.g. "30 minutes total, ending at
Home" from five minutes away).

Built as base functionality because point-to-point padded routes recur later
(quick-drive home now; non-loop navigation features afterwards).

Method: place one or two "bulge" anchors off the side of the direct start->
finish line. The further the bulge from that line, the longer the route. We
seed the bulge from a length estimate, then the generator's rescale step tunes
the perpendicular distance until the duration lands in tolerance.
"""

from __future__ import annotations

import math
from typing import List

from .geometry import (
    PROFILE_SPEED_KPH,
    destination_point,
    haversine_km,
    initial_bearing,
)
from .models import Coord


def estimate_bulge_km(start: Coord, finish: Coord, target_minutes: int,
                      profile: str) -> float:
    """Seed perpendicular bulge distance to roughly hit the target duration.

    Models the padded route as a symmetric triangle start -> bulge -> finish:
    route length approx = 2 * sqrt((d/2)^2 + bulge^2). Solve for bulge given the
    road distance the target time implies. A rough road-vs-straight factor keeps
    the seed sane; the rescale step does the precise work.
    """
    d_sf = haversine_km(start, finish)
    speed = PROFILE_SPEED_KPH.get(profile, 50.0)
    target_dist = (target_minutes / 60.0) * speed
    road_factor = 1.2  # roads are longer than straight lines
    target_leg = max(d_sf * 0.6, (target_dist / road_factor) / 2.0)
    half = d_sf / 2.0
    inside = target_leg ** 2 - half ** 2
    return math.sqrt(inside) if inside > 0 else max(0.5, d_sf * 0.3)


def _bulge_point(start: Coord, finish: Coord, along_frac: float,
                 bulge_km: float, side: int) -> Coord:
    """A point offset perpendicular from the start->finish line.

    along_frac: 0..1 position of the foot of the perpendicular along S->F.
    side: +1 or -1 for which side of the line to bulge.
    """
    b_sf = initial_bearing(start, finish)
    d_sf = haversine_km(start, finish)
    foot = destination_point(start, b_sf, d_sf * along_frac)
    perp = (b_sf + 90 * side) % 360
    return destination_point(foot, perp, bulge_km)


def build_detour_candidates(start: Coord, finish: Coord,
                            bulge_km: float) -> List[List[Coord]]:
    """A small family of distinct padded routes to the finish."""
    cands: List[List[Coord]] = []
    # Single bulge, either side, at a few along-track positions.
    for side in (+1, -1):
        for t in (0.40, 0.55, 0.70):
            cands.append([_bulge_point(start, finish, t, bulge_km, side)])
    # Two-bulge S-shape (zigzag) for extra padding with less sideways reach.
    for side in (+1, -1):
        a = _bulge_point(start, finish, 0.33, bulge_km * 0.7, side)
        b = _bulge_point(start, finish, 0.66, bulge_km * 0.7, -side)
        cands.append([a, b])
    return cands


def rescale_detour(start: Coord, finish: Coord, anchors: List[Coord],
                   scale: float) -> List[Coord]:
    """Scale only the perpendicular (bulge) component of each anchor.

    Keeps along-track progress toward the finish fixed, so the route still
    heads to the destination; only the size of the detour changes. This is the
    detour analogue of loop rescale_anchors.
    """
    b_sf = initial_bearing(start, finish)
    out: List[Coord] = []
    for a in anchors:
        d = haversine_km(start, a)
        if d < 1e-6:
            out.append(a)
            continue
        b = initial_bearing(start, a)
        ang = math.radians((b - b_sf + 540) % 360 - 180)  # signed angle to S->F
        along = d * math.cos(ang)
        cross = d * math.sin(ang) * scale
        p = destination_point(start, b_sf, max(0.0, along))
        side = 1 if cross >= 0 else -1
        p = destination_point(p, (b_sf + 90 * side) % 360, abs(cross))
        out.append(p)
    return out

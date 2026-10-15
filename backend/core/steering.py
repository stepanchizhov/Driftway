"""
Calmer drives on purpose (founder, 13 Oct 2026).

Ranking alone (scorer.calmer_lead) can only choose among the drives the
provider happened to offer, and measured on 160 Windsor candidates it
rarely changed the first drive: the candidates all pass the same lights. So
for the leading drives, this module looks for the stretch with the most
stops (traffic lights, speed bumps, roadworks that stop traffic) and tries
to go round it:

  1. find the densest stretch, away from the start and finish (a parent's
     own street can't be avoided);
  2. ask the provider for the same drive kept out of that stretch (an
     avoid-area, which only the provider understands);
  3. take the point where that detour strays furthest from the original
     drive and make it a waypoint;
  4. route the waypoints again, plainly.

Step 4 is the point. Google Maps, which most parents drive with, gets only
our waypoints and chooses its own roads between them, so a drive is only
calmer if its waypoints make it so. The avoid-area result is a search aid and
is never offered; the drive from step 4 is a candidate like any other, under
the same rules (scorer.calmer_lead).

The detour costs time, so the drive's own waypoints are pulled in to pay
for it (measured 13 Oct 2026: without that, steered 30-minute loops came
back 9 to 12 minutes long). And a steered drive is kept only if a parent
meets fewer stops on it than on the drive it came from (scorer.stops_met:
turn-arounds included; not per km, since a longer drive with more lights
is not calmer). Measured the same day on 29 Windsor detours: 6 gave a
calmer drive with the loop pulled in, 3 without. Whether the avoid-area
detour itself is calmer says little: it is forced the long way round,
while the waypoint drive is free to take a better road.

Cost: two routing calls per drive steered, MAX_STEERED drives a request.

Turning round at an easy place (founder, 13 Oct 2026). A loop that has to
double back at a waypoint usually does so mid-road, where the waypoint's
geometry happened to land: measured on 134 such turn-arounds around
Windsor, 2 were at a roundabout, turning circle or loop. The founder's own
drive ended its spike at a loop round a small island, with no three-point
turn. So for the leading drives, a waypoint the drive turns round at is
moved to the nearest easy place to turn within TURN_SHIFT_M
(calming.easy_places_near), and the drive routed again (one call), kept if
it is better on the same scale (scorer.stops_met, where an easy turn-around
counts EASY_TURN_WEIGHT).
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Callable, List, Optional, Sequence, Tuple

from .models import Coord
from .router import EvaluatedRoute
from . import calming
from .scorer import (CALM_GAIN, stop_weight, stops_met, stops_on,  # noqa: F401
                     turnaround_anchors, turnaround_count)

log = logging.getLogger("driftway")

#: Stops this close to the start or finish (along the drive) are left alone.
EDGE_M = 800.0
#: The stretch looked at, along the drive.
WINDOW_M = 2000.0
#: A stretch is worth steering round from this much "stop weight".
MIN_CLUSTER = 3.0
#: Margin round the stretch's stops for the avoid-area.
PAD_M = 120.0
#: A detour closer than this to the original drive isn't one.
MIN_DETOUR_M = 200.0
#: Leading drives steered per request.
MAX_STEERED = 2
#: Google Maps on a phone takes three waypoints.
MAX_WAYPOINTS = 3
#: A steered drive must spare at least this much (scorer.stops_met).
MIN_GAIN = CALM_GAIN
#: How far a turn-back waypoint may move to reach an easy place to turn.
TURN_SHIFT_M = 700.0
#: Leading drives whose turn-arounds are moved, per request.
MAX_TURN_MOVES = 2
#: A drive with a moved turn-around must gain at least this (an easy
#: turn-around instead of a hard one gains 0.7).
TURN_GAIN = 0.3
#: Points compared when finding the apex: enough for a 200 m test on a
#: 40 km drive, few enough to stay quick.
APEX_POINTS = 250

Box = Tuple[float, float, float, float]          # south, west, north, east


def _xy(lat: float, lng: float, k: float) -> Tuple[float, float]:
    return lng * k * 111320.0, lat * 111320.0


def _cumulative(pts: Sequence[Tuple[float, float]], k: float) -> List[float]:
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        (ax, ay), (bx, by) = _xy(*a, k), _xy(*b, k)
        cum.append(cum[-1] + math.hypot(bx - ax, by - ay))
    return cum


def _nearest_index(pts: Sequence[Tuple[float, float]], lat: float, lng: float, k: float) -> int:
    return min(range(len(pts)), key=lambda j: (pts[j][0] - lat) ** 2 + ((pts[j][1] - lng) * k) ** 2)


def busiest_stretch(route: EvaluatedRoute) -> Optional[Box]:
    """The box round the drive's densest WINDOW_M of stops, or None when no
    stretch reaches MIN_CLUSTER, or its box would take in the start, the
    finish or a waypoint (the provider can't avoid those)."""
    pts = [(p.lat, p.lng) for p in route.geometry]
    if len(pts) < 2:
        return None
    k = math.cos(math.radians(pts[0][0]))
    total = _cumulative(pts, k)[-1]
    stops = [s for s in stops_on(route) if EDGE_M <= s[0] <= total - EDGE_M]
    best, best_w, j, w = None, 0.0, 0, 0.0
    for i, stop in enumerate(stops):            # window [j..i] within WINDOW_M
        w += stop[3]
        while stop[0] - stops[j][0] > WINDOW_M:
            w -= stops[j][3]
            j += 1
        if w > best_w:
            best, best_w = stops[j:i + 1], w
    if not best or best_w < MIN_CLUSTER:
        return None
    dlat, dlng = PAD_M / 111320.0, PAD_M / (111320.0 * k)
    box = (min(s[1] for s in best) - dlat, min(s[2] for s in best) - dlng,
           max(s[1] for s in best) + dlat, max(s[2] for s in best) + dlng)
    keep_out = [pts[0], pts[-1], *((a.lat, a.lng) for a in route.anchors)]
    if any(box[0] <= lat <= box[2] and box[1] <= lng <= box[3] for lat, lng in keep_out):
        return None
    return box


def _seg_dist(p, a, b) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(ax + t * dx - px, ay + t * dy - py)


def _thin(points: Sequence[Coord], n: int) -> List[Coord]:
    step = max(1, len(points) // n)
    return list(points[::step]) + ([points[-1]] if (len(points) - 1) % step else [])


def detour_apex(original: Sequence[Coord], detour: Sequence[Coord]) -> Optional[Coord]:
    """The point of the detour furthest from the original drive; None if
    the detour never leaves it by MIN_DETOUR_M. Looked for along the whole
    detour: going round one stretch can change the drive far from it."""
    if len(original) < 2 or not detour:
        return None
    k = math.cos(math.radians(original[0].lat))
    orig = [_xy(p.lat, p.lng, k) for p in _thin(original, APEX_POINTS)]
    segs = list(zip(orig, orig[1:]))
    best, best_d = None, MIN_DETOUR_M
    for p in _thin(detour, APEX_POINTS):
        xy = _xy(p.lat, p.lng, k)
        d = min(_seg_dist(xy, a, b) for a, b in segs)
        if d > best_d:
            best, best_d = p, d
    return best


def with_waypoint(anchors: List[Coord], detour: Sequence[Coord], apex: Coord,
                  placed: Optional[List[Coord]] = None) -> List[Coord]:
    """The anchors with the apex added in driving order (along the detour).
    Over MAX_WAYPOINTS, the anchor nearest the apex along the drive gives way.
    `placed`, if given, are the anchors as moved (pulled in), in the same
    order as `anchors`, which still decide the order."""
    pts = [(p.lat, p.lng) for p in detour]
    k = math.cos(math.radians(pts[0][0]))
    placed = placed or anchors
    order = [(_nearest_index(pts, a.lat, a.lng, k), False, b) for a, b in zip(anchors, placed)]
    at = _nearest_index(pts, apex.lat, apex.lng, k)
    if len(order) >= MAX_WAYPOINTS:
        drop = min(order, key=lambda o: abs(o[0] - at))
        order.remove(drop)
    order.append((at, True, apex))
    return [a for _i, _new, a in sorted(order, key=lambda o: (o[0], o[1]))]


def _pull_in(target_minutes: float, detour_minutes: float) -> float:
    """How far to pull the drive's own waypoints in to pay for the detour's
    extra time (the refiner's damped correction, never pushing out)."""
    if detour_minutes <= target_minutes + 1.0:
        return 1.0
    return max(0.5, (target_minutes / detour_minutes) ** 0.75)


async def calmer_candidates(router, start: Coord, finish: Coord,
                            leading: List[EvaluatedRoute], profile: str,
                            target_minutes: float,
                            rescale: Callable[[List[Coord], float], List[Coord]]
                            ) -> List[EvaluatedRoute]:
    """Drives that go round the busiest stretch of the leading drives, as
    plain waypoints, each calmer than the drive it came from. Empty when the
    router can't avoid areas (simulated routing), or nothing is worth
    steering round. `rescale(anchors, scale)` pulls waypoints in (loops and
    detours scale differently)."""
    avoid = getattr(router, "evaluate_avoiding", None)
    if avoid is None:
        return []
    plans = []
    for route in leading:
        box = busiest_stretch(route)
        if box is not None:
            plans.append((route, box))
        if len(plans) >= MAX_STEERED:
            break
    if not plans:
        return []
    detours = await asyncio.gather(
        *(avoid(start, finish, route.anchors, profile, [box]) for route, box in plans),
        return_exceptions=True)
    bases, waypoint_sets = [], []
    for (route, box), det in zip(plans, detours):
        if not isinstance(det, EvaluatedRoute) or not det.geometry:
            continue
        apex = detour_apex(route.geometry, det.geometry)
        if apex is None:
            continue
        anchors = list(route.anchors)
        placed = rescale(anchors, _pull_in(target_minutes, det.minutes))
        bases.append(route)
        waypoint_sets.append(with_waypoint(anchors, det.geometry, apex, placed))
    if not waypoint_sets:
        return []
    got = await asyncio.gather(*(router.evaluate(start, finish, a, profile) for a in waypoint_sets),
                               return_exceptions=True)
    out = []
    for base, g in zip(bases, got):
        if not isinstance(g, EvaluatedRoute):
            continue
        if stops_met(g) <= stops_met(base) - MIN_GAIN:
            g.steered = True
            g.built_by = "steered"
            out.append(g)
    return out


def easier_turn_waypoints(route: EvaluatedRoute) -> Optional[List[Coord]]:
    """The drive's waypoints with each one it turns round at, away from any
    easy place to turn, moved to the nearest easy place within TURN_SHIFT_M;
    None when there is nothing to move."""
    anchors = list(route.anchors)
    moved = False
    for i, p in turnaround_anchors(route):
        if calming.easy_turn_at(p.lat, p.lng):
            continue
        near = calming.easy_places_near(p.lat, p.lng, TURN_SHIFT_M)
        if near:
            _d, lat, lng, _kind = near[0]
            anchors[i] = Coord(lat=lat, lng=lng)
            moved = True
    return anchors if moved else None


async def easier_turn_candidates(router, start: Coord, finish: Coord,
                                 leading: List[EvaluatedRoute], profile: str) -> List[EvaluatedRoute]:
    """The leading drives with their turn-arounds moved to easy places to
    turn, each kept only if it is better on the stops scale."""
    plans = []
    for route in leading:
        anchors = easier_turn_waypoints(route)
        if anchors is not None:
            plans.append((route, anchors))
        if len(plans) >= MAX_TURN_MOVES:
            break
    if not plans:
        return []
    got = await asyncio.gather(*(router.evaluate(start, finish, a, profile) for _r, a in plans),
                               return_exceptions=True)
    out = []
    for (base, _a), g in zip(plans, got):
        if isinstance(g, EvaluatedRoute) and stops_met(g) <= stops_met(base) - TURN_GAIN:
            g.steered = True
            g.built_by = "turn_moved"
            out.append(g)
    return out

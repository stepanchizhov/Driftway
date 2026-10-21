"""
Holding a drive to its own roads when it is handed to Google Maps
(founder, 21 Oct 2026, after a drive west of London: Driftway planned 71
minutes on quieter roads, Google drove 52 on the M4 and M25. "We need to use
all the checkpoints we have if needed.").

A Google Maps link carries the start, the finish and at most three points in
between (Maps URLs, mobile). Between them Google takes its own fastest way,
and nothing in the link says "avoid motorways". So the link's spare points
are spent where it matters: Driftway asks the router for the plain fastest
way through the link's points (nothing avoided: what a navigation app would
do), finds where Driftway's own route strays furthest from it, and pins a
point there, on Driftway's road. Again until the link is full or the two
agree to within OFF_ROUTE_M.

The plain fastest way is TomTom's, not Google's: a stand-in until the
comparison with Google (tools/google_compare.py) says how close they are.
Each pin costs one routing call.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import List, Optional, Sequence, Tuple

from .geometry import haversine_km
from .models import Coord

log = logging.getLogger("driftway")

#: Waypoints a Google Maps link carries on mobile.
LINK_MAX = 3
#: Driftway's route this far from the plain fastest way is a different road.
OFF_ROUTE_M = 400.0
#: Divergence this close to the start or finish isn't worth a pin: it is the
#: way out of the street.
END_SKIP_M = 600.0
#: A full link whose stand-in follows less of the drive than this tries
#: swapping one of its points for a pin.
SWAP_BELOW = 0.9
#: Points of Driftway's route looked at, at most.
SAMPLES = 400
_CELL = 0.002          # degrees: about 220 m north-south, 140 m east-west here


def _m(a: Coord, b: Coord) -> float:
    return haversine_km(a, b) * 1000.0


def _offs(ours: Sequence[Coord], theirs: Sequence[Coord]) -> List[Tuple[int, float]]:
    """For a sample of our route (its ends left out), how far each point is
    from their route, in metres. Near points are measured against their
    neighbours in a grid; a point with none within about 450 m, against a
    sample of their whole route, so a detour's middle is its farthest."""
    if len(ours) < 2 or not theirs:
        return []
    grid = defaultdict(list)
    for q in theirs:
        grid[(int(math.floor(q.lat / _CELL)), int(math.floor(q.lng / _CELL)))].append(q)
    sample = list(theirs[::max(1, len(theirs) // SAMPLES)])
    start, end = ours[0], ours[-1]
    out = []
    for i in range(0, len(ours), max(1, len(ours) // SAMPLES)):
        p = ours[i]
        if _m(p, start) < END_SKIP_M or _m(p, end) < END_SKIP_M:
            continue
        ci, cj = int(math.floor(p.lat / _CELL)), int(math.floor(p.lng / _CELL))
        d = min((_m(p, q) for di in range(-2, 3) for dj in range(-3, 4)
                 for q in grid.get((ci + di, cj + dj), ())), default=None)
        out.append((i, d if d is not None else min(_m(p, q) for q in sample)))
    return out


def followed(ours: Sequence[Coord], theirs: Sequence[Coord]) -> float:
    """Share of our route their route follows (within OFF_ROUTE_M)."""
    offs = _offs(ours, theirs)
    return sum(1 for _, d in offs if d < OFF_ROUTE_M) / len(offs) if offs else 1.0


def farthest_off(ours: Sequence[Coord], theirs: Sequence[Coord]) -> Tuple[int, float]:
    """The point of our route farthest from their route (index into ours),
    and how far, in metres; (-1, 0) when there is nothing to compare."""
    return max(_offs(ours, theirs), key=lambda o: o[1], default=(-1, 0.0))


def _position(p: Coord, route: Sequence[Coord]) -> int:
    """Index of the route point nearest p."""
    return min(range(len(route)), key=lambda i: (route[i].lat - p.lat) ** 2 + (route[i].lng - p.lng) ** 2)


def _ordered(placed: List[Tuple[int, Coord]]) -> List[Coord]:
    """Points by where they are along the drive. A pin's place is known (it
    is a point of the route): on a road driven out and back, the nearest
    point could be the wrong pass."""
    return [p for _, p in sorted(placed, key=lambda ip: ip[0])]


async def link_points(router, start: Coord, finish: Coord, route: Sequence[Coord],
                      anchors: List[Coord]) -> List[Coord]:
    """The points for the drive's navigation link: its anchors, plus pins on
    its own roads where a navigation app would otherwise leave them, up to
    LINK_MAX. The anchors alone when the router can't say what the plain
    fastest way would be."""
    placed = [(_position(a, route), a) for a in list(anchors)[:LINK_MAX]] if len(route) >= 2 else []
    points = [a for a in list(anchors)[:LINK_MAX]]
    ask = getattr(router, "evaluate_as_navigation", None)
    if ask is None or len(route) < 2:
        return points
    points = _ordered(placed)
    # Each set of points is scored by how much of the drive the stand-in
    # follows through them; the best is kept, so a pin that moves the
    # trouble elsewhere (seen live 22 Oct 2026) isn't used.
    best, best_share, best_guess, best_placed = points, -1.0, None, placed

    async def stand_in(pts):
        try:
            guess = await ask(start, finish, pts)
        except Exception as e:  # noqa: BLE001 - a link without pins still works
            log.warning("navigation stand-in failed: %s", type(e).__name__)
            return None
        return guess if guess is not None and guess.geometry else None

    while True:
        guess = await stand_in(points)
        if guess is None:
            break
        share = followed(route, guess.geometry)
        if share > best_share + 0.02:
            best, best_share, best_guess, best_placed = points, share, guess, placed
        if len(points) >= LINK_MAX:
            break
        i, off = farthest_off(route, guess.geometry)
        if i < 0 or off < OFF_ROUTE_M:
            break
        placed = placed + [(i, route[i])]
        points = _ordered(placed)

    # Full, and still straying (a loop's three turning points leave no spare
    # one): swap each point in turn for a pin where it strays most, once.
    if best_guess is not None and len(best) >= LINK_MAX and best_share < SWAP_BELOW:
        i, off = farthest_off(route, best_guess.geometry)
        if i >= 0 and off >= OFF_ROUTE_M:
            base = sorted(best_placed, key=lambda ip: ip[0])
            for j in range(len(base)):
                swap = _ordered([ip for k, ip in enumerate(base) if k != j] + [(i, route[i])])
                guess = await stand_in(swap)
                if guess is None:
                    continue
                share = followed(route, guess.geometry)
                if share > best_share + 0.02:
                    best, best_share = swap, share
    return best


def changed(anchors: Sequence[Coord], points: Optional[Sequence[Coord]]) -> bool:
    """Whether the link differs from the anchors (pins added or swapped in)."""
    return points is not None and [(p.lat, p.lng) for p in points] != [(a.lat, a.lng) for a in anchors]

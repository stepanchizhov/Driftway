"""
Mapped speed bumps and traffic lights along a drive (docs/CALMER_DRIVES.md).

Neither route provider can avoid speed bumps or traffic lights, so Driftway
counts the ones OpenStreetMap maps along each candidate drive it already
has, ranks with that, and says the numbers on the card. The data is
prepared ahead of time by tools/build_calming.py into
data/calming/<region>.json; nothing is fetched while serving a drive.

A count is only as good as the mapping: a hump nobody mapped is not counted.
So the card says "mapped", never "none", and a drive outside every prepared
region gets no count at all rather than a zero.

Easy places to turn round (founder, 13 Oct 2026) come from the same data:
roundabouts, mini-roundabouts, turning circles and road loops round an
island (easy_turn_at); a turn-around at one needs no three-point turn.

Traffic lights (founder, 12 Oct 2026) come in groups: every light of a
junction, or both sides of a crossing, share a group, and a drive passing
any of them counts the group once. Junction lights and pedestrian-operated
lights are counted apart.
"""

from __future__ import annotations

import glob
import json
import logging
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

log = logging.getLogger("driftway")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "calming")
#: A mapped point this close to the route is on it. Bumps and lights are
#: mapped on the road's centre line, and provider geometry follows it closely.
NEAR_M = 12.0
#: Grid cell for the index, in degrees (about 55 m of latitude).
CELL = 0.0005
#: At least this share of the drive must lie inside prepared regions for a
#: count to mean anything.
MIN_COVERED = 0.8
ATTRIBUTION = "Speed bumps and traffic lights: © OpenStreetMap contributors"
#: A turn-around this close to the edge of an easy place to turn is at it.
TURN_NEAR_M = 30.0
#: Cells searched round a point for easy places to turn (a big roundabout
#: can be 150 m across).
TURN_CELLS = 3


@dataclass(frozen=True)
class BumpCount:
    count: int
    #: Kilometres of the drive inside prepared regions.
    covered_km: float
    #: Share of the drive inside them.
    covered_share: float

    @property
    def per_km(self) -> float:
        return self.count / self.covered_km if self.covered_km > 0 else 0.0


@dataclass(frozen=True)
class LightCount:
    #: Junctions with traffic lights the drive goes through.
    junctions: int
    #: Pedestrian-operated lights (pelican, puffin, toucan, signal-controlled
    #: crossings) not part of a junction.
    pedestrian: int
    covered_km: float

    @property
    def total(self) -> int:
        return self.junctions + self.pedestrian

    @property
    def per_km(self) -> float:
        return self.total / self.covered_km if self.covered_km > 0 else 0.0


class _Index:
    def __init__(self, regions: List[dict]):
        self.boxes: List[Tuple[float, float, float, float]] = []
        self.cells: Dict[Tuple[int, int], List[Tuple[float, float, str]]] = defaultdict(list)
        #: Lights: (lat, lng, kind, group), the group unique across regions.
        self.lights: Dict[Tuple[int, int], List[Tuple[float, float, str, str]]] = defaultdict(list)
        self.has_lights: List[Tuple[float, float, float, float]] = []
        #: Easy places to turn round: (lat, lng, kind, radius_m).
        self.turns: Dict[Tuple[int, int], List[Tuple[float, float, str, float]]] = defaultdict(list)
        self.as_of: List[str] = []
        for n, r in enumerate(regions):
            box = tuple(r["bbox"])
            self.boxes.append(box)
            self.as_of.append(r.get("as_of", ""))
            for lat, lng, kind in r["points"]:
                self.cells[(int(lat / CELL), int(lng / CELL))].append((lat, lng, kind))
            for t in r.get("turns", []):
                # [lat, lng, kind, radius, public]. Only a place on a road
                # known to be open to cars counts (15 Oct 2026); data built
                # before then has no such evidence and counts for nothing.
                if len(t) >= 5 and t[4]:
                    lat, lng, kind, radius = t[:4]
                    self.turns[(int(lat / CELL), int(lng / CELL))].append((lat, lng, kind, float(radius)))
            if "signals" in r:
                self.has_lights.append(box)
                for lat, lng, kind, group in r["signals"]:
                    self.lights[(int(lat / CELL), int(lng / CELL))].append((lat, lng, kind, f"{n}:{group}"))

    def covers(self, lat: float, lng: float, boxes=None) -> bool:
        return any(s <= lat <= n and w <= lng <= e for s, w, n, e in (boxes if boxes is not None else self.boxes))


_index: Optional[_Index] = None


def load(directory: str = DATA_DIR) -> _Index:
    """Read every prepared region once. A missing or unreadable file means
    no counts for that area, never an error for a drive."""
    global _index
    if _index is None or directory != DATA_DIR:
        regions = []
        for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
            try:
                with open(path, encoding="utf-8") as f:
                    regions.append(json.load(f))
            except Exception as e:  # noqa: BLE001
                log.error("calming data unreadable (%s): %s", os.path.basename(path), type(e).__name__)
        idx = _Index(regions)
        if directory != DATA_DIR:
            return idx
        _index = idx
    return _index


def _metres(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


class _Route:
    """A drive's segments, indexed by grid cell, with its coverage."""

    def __init__(self, geometry: Sequence, boxes):
        pts = [(p.lat, p.lng) if hasattr(p, "lat") else (p[0], p[1]) for p in geometry]
        self.ok = len(pts) >= 2 and bool(boxes)
        self.total = self.covered = 0.0
        self.cells: Dict[Tuple[int, int], List[int]] = defaultdict(list)
        self.segs = []
        if not self.ok:
            return
        self.k = math.cos(math.radians(pts[0][0]))
        inside = lambda p: any(s <= p[0] <= n and w <= p[1] <= e for s, w, n, e in boxes)  # noqa: E731
        for a, b in zip(pts, pts[1:]):
            d = _metres(a, b)
            self.total += d
            if inside(a) and inside(b):
                self.covered += d
            i = len(self.segs)
            self.segs.append(((a[1] * self.k * 111320.0, a[0] * 111320.0),
                              (b[1] * self.k * 111320.0, b[0] * 111320.0)))
            # Every cell the segment's box touches, so long straight segments
            # are found too.
            ci0, ci1 = sorted((int(a[0] / CELL), int(b[0] / CELL)))
            cj0, cj1 = sorted((int(a[1] / CELL), int(b[1] / CELL)))
            if (ci1 - ci0 + 1) * (cj1 - cj0 + 1) <= 400:
                for ci in range(ci0, ci1 + 1):
                    for cj in range(cj0, cj1 + 1):
                        self.cells[(ci, cj)].append(i)

    @property
    def counts(self) -> bool:
        return self.ok and self.total > 0 and self.covered / self.total >= MIN_COVERED

    def on_route(self, lat: float, lng: float, seg_ids) -> bool:
        px, py = lng * self.k * 111320.0, lat * 111320.0
        for s in seg_ids:
            (ax, ay), (bx, by) = self.segs[s]
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
            if math.hypot(ax + t * dx - px, ay + t * dy - py) <= NEAR_M:
                return True
        return False

    def hits(self, cells):
        """Every mapped item within NEAR_M of the drive, each once."""
        seen = set()
        for (ci, cj), seg_ids in self.cells.items():
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    for item in cells.get((ci + di, cj + dj), ()):
                        if item in seen:
                            continue
                        if self.on_route(item[0], item[1], seg_ids):
                            seen.add(item)
        return seen


def stops_along(geometry: Sequence, index: Optional[_Index] = None) -> List[Tuple[float, float, float, str]]:
    """Where the drive meets each mapped bump and each group of lights:
    (metres from the start, lat, lng, kind), kind "bump", "junction" or
    "pedestrian", in driving order. Used to find the stretch worth steering
    round (core/steering.py); empty outside the prepared data."""
    idx = index or load()
    pts = [(p.lat, p.lng) if hasattr(p, "lat") else (p[0], p[1]) for p in geometry]
    route = _Route(pts, idx.boxes)
    if not route.counts:
        return []
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + _metres(a, b))

    def along(lat: float, lng: float) -> float:
        # The nearest vertex is close enough: provider geometry has a point
        # every few tens of metres.
        i = min(range(len(pts)), key=lambda j: (pts[j][0] - lat) ** 2 + ((pts[j][1] - lng) * route.k) ** 2)
        return cum[i]

    out = [(along(lat, lng), lat, lng, "bump") for lat, lng, _kind in route.hits(idx.cells)]
    first: Dict[str, Tuple[float, float, float, str]] = {}
    for lat, lng, kind, group in route.hits(idx.lights):
        s = along(lat, lng)
        if group not in first or s < first[group][0]:
            first[group] = (s, lat, lng, kind)
    out.extend(first.values())
    return sorted(out)


def easy_turn_at(lat: float, lng: float, index: Optional[_Index] = None) -> Optional[str]:
    """The kind of easy place to turn round at this point ("roundabout",
    "mini_roundabout", "turning_circle", "loop"), or None."""
    idx = index or load()
    ci, cj = int(lat / CELL), int(lng / CELL)
    best = None
    for di in range(-TURN_CELLS, TURN_CELLS + 1):
        for dj in range(-TURN_CELLS, TURN_CELLS + 1):
            for t_lat, t_lng, kind, radius in idx.turns.get((ci + di, cj + dj), ()):
                d = _metres((lat, lng), (t_lat, t_lng)) - radius
                if d <= TURN_NEAR_M and (best is None or d < best[0]):
                    best = (d, kind)
    return best[1] if best else None


def easy_places_near(lat: float, lng: float, within_m: float,
                     index: Optional[_Index] = None) -> List[Tuple[float, float, float, str]]:
    """Easy places to turn round within `within_m` of a point, nearest
    first: (metres, lat, lng, kind)."""
    idx = index or load()
    ci, cj = int(lat / CELL), int(lng / CELL)
    reach = int(within_m / (CELL * 111320.0)) + 2
    out = []
    for di in range(-reach, reach + 1):
        for dj in range(-reach, reach + 1):
            for t_lat, t_lng, kind, _radius in idx.turns.get((ci + di, cj + dj), ()):
                d = _metres((lat, lng), (t_lat, t_lng))
                if d <= within_m:
                    out.append((d, t_lat, t_lng, kind))
    return sorted(out)


def count_along(geometry: Sequence, index: Optional[_Index] = None) -> Optional[BumpCount]:
    """Mapped speed bumps within NEAR_M of the drive, each counted once, or
    None when too little of the drive lies inside prepared regions.

    `geometry` is a sequence of points with .lat/.lng (models.Coord) or
    (lat, lng) pairs."""
    idx = index or load()
    route = _Route(geometry, idx.boxes)
    if not route.counts:
        return None
    return BumpCount(count=len(route.hits(idx.cells)), covered_km=route.covered / 1000.0,
                     covered_share=route.covered / route.total)


def lights_along(geometry: Sequence, index: Optional[_Index] = None) -> Optional[LightCount]:
    """Junctions with traffic lights and pedestrian-operated lights on the
    drive, each junction or crossing counted once, or None outside data
    that includes lights."""
    idx = index or load()
    route = _Route(geometry, idx.has_lights)
    if not route.counts:
        return None
    groups: Dict[str, str] = {}
    for _lat, _lng, kind, group in route.hits(idx.lights):
        groups[group] = kind
    kinds: List[str] = list(groups.values())
    return LightCount(junctions=kinds.count("junction"), pedestrian=kinds.count("pedestrian"),
                      covered_km=route.covered / 1000.0)

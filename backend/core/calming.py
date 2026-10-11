"""
Mapped speed bumps along a drive (docs/CALMER_DRIVES.md, 11 Oct 2026).

Neither route provider can avoid speed bumps, so Driftway counts the ones
OpenStreetMap maps along each candidate drive it already has, ranks with
that, and says the number on the card. The data is prepared ahead of time by
tools/build_calming.py into data/calming/<region>.json; nothing is fetched
while serving a drive.

A count is only as good as the mapping: a hump nobody mapped is not counted.
So the card says "mapped", never "none", and a drive outside every prepared
region gets no count at all rather than a zero.
"""

from __future__ import annotations

import glob
import json
import logging
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

log = logging.getLogger("driftway")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "calming")
#: A mapped point this close to the route is on it. Bumps are mapped on the
#: road's centre line, and provider geometry follows it closely.
NEAR_M = 12.0
#: Grid cell for the index, in degrees (about 55 m of latitude).
CELL = 0.0005
#: At least this share of the drive must lie inside prepared regions for a
#: count to mean anything.
MIN_COVERED = 0.8
ATTRIBUTION = "Speed bumps: © OpenStreetMap contributors"


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


class _Index:
    def __init__(self, regions: List[dict]):
        self.boxes: List[Tuple[float, float, float, float]] = []
        self.cells: Dict[Tuple[int, int], List[Tuple[float, float]]] = defaultdict(list)
        self.as_of: List[str] = []
        for r in regions:
            self.boxes.append(tuple(r["bbox"]))
            self.as_of.append(r.get("as_of", ""))
            for lat, lng, _kind in r["points"]:
                self.cells[(int(lat / CELL), int(lng / CELL))].append((lat, lng))

    def covers(self, lat: float, lng: float) -> bool:
        return any(s <= lat <= n and w <= lng <= e for s, w, n, e in self.boxes)


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
                log.error("speed-bump data unreadable (%s): %s", os.path.basename(path), type(e).__name__)
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


def count_along(geometry: Sequence, index: Optional[_Index] = None) -> Optional[BumpCount]:
    """Mapped speed bumps within NEAR_M of the drive, each counted once, or
    None when too little of the drive lies inside prepared regions.

    `geometry` is a sequence of points with .lat/.lng (models.Coord) or
    (lat, lng) pairs."""
    idx = index or load()
    pts = [(p.lat, p.lng) if hasattr(p, "lat") else (p[0], p[1]) for p in geometry]
    if len(pts) < 2 or not idx.boxes:
        return None

    total = covered = 0.0
    k = math.cos(math.radians(pts[0][0]))
    seg_cells: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    segs = []
    for a, b in zip(pts, pts[1:]):
        d = _metres(a, b)
        total += d
        if idx.covers(*a) and idx.covers(*b):
            covered += d
        i = len(segs)
        segs.append(((a[1] * k * 111320.0, a[0] * 111320.0), (b[1] * k * 111320.0, b[0] * 111320.0)))
        # Every cell the segment's box touches, so long straight segments are
        # found too.
        ci0, ci1 = sorted((int(a[0] / CELL), int(b[0] / CELL)))
        cj0, cj1 = sorted((int(a[1] / CELL), int(b[1] / CELL)))
        if (ci1 - ci0 + 1) * (cj1 - cj0 + 1) <= 400:
            for ci in range(ci0, ci1 + 1):
                for cj in range(cj0, cj1 + 1):
                    seg_cells[(ci, cj)].append(i)
    if total <= 0 or covered / total < MIN_COVERED:
        return None

    count = 0
    seen = set()
    for (ci, cj), seg_ids in seg_cells.items():
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for lat, lng in idx.cells.get((ci + di, cj + dj), ()):
                    if (lat, lng) in seen:
                        continue
                    px, py = lng * k * 111320.0, lat * 111320.0
                    for s in seg_ids:
                        (ax, ay), (bx, by) = segs[s]
                        dx, dy = bx - ax, by - ay
                        L2 = dx * dx + dy * dy
                        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
                        if math.hypot(ax + t * dx - px, ay + t * dy - py) <= NEAR_M:
                            seen.add((lat, lng))
                            count += 1
                            break
    return BumpCount(count=count, covered_km=covered / 1000.0, covered_share=covered / total)

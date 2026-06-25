"""
Geodesic helpers and loop-shape generation.

The core problem: routing APIs expect destinations, but we want a *loop*.
We solve it by placing 2-3 intermediate anchor points around the start, so
the route start -> anchors -> finish traces a closed-ish shape. The routing
provider fills in the actual roads between anchors.

All maths uses the spherical-earth approximation, which is accurate to well
within a few metres at the scale of a nap drive (tens of km). That is far
below the noise introduced by real roads and traffic, so it is plenty.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List

from .models import Coord, Direction

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class Shape:
    """A loop template: a list of (bearing_offset_deg, radius_factor) anchors.

    bearing_offset is relative to the loop's main bearing.
    radius_factor scales the base radius for that anchor (lets us make
    teardrops, bulges, etc.).
    """
    name: str
    anchors: List[tuple]  # list of (bearing_offset_deg, radius_factor)


# A small family of distinct loop shapes. Each produces a genuinely different
# road journey once the provider routes through the anchors.
SHAPES: List[Shape] = [
    # Wide triangle: out one way, across, back. Good all-rounder.
    Shape("triangle", [(-55, 1.0), (55, 1.0)]),
    # Rounded triangle: three anchors, middle one bulges outward.
    Shape("rounded_triangle", [(-60, 0.95), (0, 1.25), (60, 0.95)]),
    # Teardrop: narrow, elongated loop pointing in the main bearing.
    Shape("teardrop", [(-22, 1.15), (22, 1.15)]),
    # Asymmetric: lopsided loop, useful for variety / avoiding a sector.
    Shape("asymmetric", [(-35, 1.3), (40, 0.8)]),
]


def destination_point(origin: Coord, bearing_deg: float, distance_km: float) -> Coord:
    """Return the point reached by travelling distance_km from origin along bearing."""
    ang = distance_km / EARTH_RADIUS_KM           # angular distance (radians)
    brng = math.radians(bearing_deg)
    lat1 = math.radians(origin.lat)
    lng1 = math.radians(origin.lng)

    lat2 = math.asin(
        math.sin(lat1) * math.cos(ang)
        + math.cos(lat1) * math.sin(ang) * math.cos(brng)
    )
    lng2 = lng1 + math.atan2(
        math.sin(brng) * math.sin(ang) * math.cos(lat1),
        math.cos(ang) - math.sin(lat1) * math.sin(lat2),
    )
    return Coord(lat=math.degrees(lat2), lng=((math.degrees(lng2) + 540) % 360) - 180)


def haversine_km(a: Coord, b: Coord) -> float:
    """Great-circle distance between two coords, in km."""
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlng = math.radians(b.lng - a.lng)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


# Average road speed (km/h) used only to seed the initial radius guess.
# The rescale loop corrects for reality, so these just need to be in the
# right ballpark for each profile. HYPOTHESIS: tune from real ride data.
PROFILE_SPEED_KPH = {
    "motorway": 85.0,
    "mixed": 50.0,
    "quiet": 35.0,
}

# Fraction of "ideal straight-line distance" that becomes anchor radius.
# A loop's road distance is much larger than the start->anchor radius, so
# this factor is small. Seed value only; the rescale step does the real work.
LOOP_RADIUS_FACTOR = 0.28


def estimate_radius_km(target_minutes: int, profile: str) -> float:
    speed = PROFILE_SPEED_KPH.get(profile, 50.0)
    road_distance = (target_minutes / 60.0) * speed
    return road_distance * LOOP_RADIUS_FACTOR


def bearings_for_direction(direction: Direction) -> List[float]:
    """Main bearings to try, given an optional direction preference.

    SURPRISE explores all around; a cardinal direction biases toward that
    sector (useful for avoiding a known town in the opposite direction).
    """
    if direction == Direction.SURPRISE:
        return [0, 60, 120, 180, 240, 300]
    centre = {"N": 0, "E": 90, "S": 180, "W": 270}[direction.value]
    return [(centre + off) % 360 for off in (-30, 0, 30)]


def build_candidate(start: Coord, main_bearing: float, radius_km: float,
                    shape: Shape) -> List[Coord]:
    """Produce the intermediate anchor coords for one candidate loop."""
    anchors: List[Coord] = []
    for offset, factor in shape.anchors:
        b = (main_bearing + offset) % 360
        anchors.append(destination_point(start, b, radius_km * factor))
    return anchors


def rescale_anchors(start: Coord, anchors: List[Coord], scale: float) -> List[Coord]:
    """Move each anchor closer to / further from start by `scale`.

    Used by the binary-search-style duration correction: if a route came back
    too long, scale < 1 pulls anchors inward; too short, scale > 1 pushes out.
    Preserves bearings so the loop shape is kept.
    """
    out: List[Coord] = []
    for a in anchors:
        d = haversine_km(start, a) * scale
        b = initial_bearing(start, a)
        out.append(destination_point(start, b, d))
    return out


def initial_bearing(a: Coord, b: Coord) -> float:
    """Forward azimuth from a to b, in degrees (0-360)."""
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlng = math.radians(b.lng - a.lng)
    y = math.sin(dlng) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlng)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

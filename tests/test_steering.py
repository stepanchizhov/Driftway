"""
Calmer drives on purpose (core/steering.py; founder, 13 Oct 2026): go round
the busiest stretch of stops on a leading drive, as plain waypoints that
Google Maps can follow, and keep the result only if it is calmer.

A synthetic world, nobody's address: a rectangular loop near 52.0 N 13.0 E,
with a cluster of speed bumps half-way up its western side and a quiet
parallel road 700 m further west.
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import httpx  # noqa: E402

from core import calming, steering  # noqa: E402
from core import router as R  # noqa: E402
from core.geometry import rescale_anchors  # noqa: E402
from core.models import Coord, RoadMix  # noqa: E402
from core.router import EvaluatedRoute, MockRouter  # noqa: E402

BBOX = [51.99, 12.97, 52.05, 13.04]
START = Coord(lat=52.0, lng=13.0)
NW, NE = Coord(lat=52.04, lng=13.0), Coord(lat=52.04, lng=13.03)
QUIET_LNG = 12.99


def line(a, b, n=40):
    return [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n)]


def path(*corners):
    pts = []
    for a, b in zip(corners, corners[1:]):
        pts += line(a, b)
    pts.append(corners[-1])
    return [Coord(lat=p[0], lng=p[1]) for p in pts]


# The loop: up the western side (through the bumps), across, down, back.
BASE = path((52.0, 13.0), (52.04, 13.0), (52.04, 13.03), (52.0, 13.03), (52.0, 13.0))
# The same loop, up the quiet road instead.
CALM = path((52.0, 13.0), (52.0, QUIET_LNG), (52.04, QUIET_LNG), (52.04, 13.0),
            (52.04, 13.03), (52.0, 13.03), (52.0, 13.0))
BUMPS = [[52.018, 13.0, "hump"], [52.020, 13.0, "hump"], [52.022, 13.0, "table"], [52.024, 13.0, "hump"]]


def region(points):
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "test.json"), "w", encoding="utf-8") as f:
        json.dump({"region": "test", "bbox": BBOX, "as_of": "2026-10-13", "points": points,
                   "signals": []}, f)
    return calming.load(d)


def route(geometry, anchors, minutes=30.0, uturn=False):
    return EvaluatedRoute(anchors=list(anchors), minutes=minutes, distance_km=13.0,
                          road_mix=RoadMix(), geometry=geometry, has_uturn=uturn, works=[])


class FakeRouter:
    """Avoids the box by taking the quiet road; routes plainly through the
    quiet road only when a waypoint is on it (or never, if stubborn)."""
    name = "fake"

    def __init__(self, stubborn=False):
        self.stubborn = stubborn
        self.avoided, self.routed = [], []

    async def evaluate_avoiding(self, start, finish, anchors, profile, boxes):
        self.avoided.append(boxes)
        return route(CALM, anchors, minutes=31.0)

    async def evaluate(self, start, finish, anchors, profile):
        self.routed.append(anchors)
        on_quiet = any(abs(a.lng - QUIET_LNG) < 0.002 for a in anchors)
        return route(CALM if on_quiet and not self.stubborn else BASE, anchors, minutes=31.0)


class _Base(unittest.TestCase):
    bumps = BUMPS

    def setUp(self):
        self.patch = mock.patch.object(calming, "_index", region(self.bumps))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def steer(self, router, leading):
        return asyncio.run(steering.calmer_candidates(
            router, START, START, leading, "quiet", 30,
            lambda a, s: rescale_anchors(START, a, s)))


class FindingTests(_Base):
    def test_the_busiest_stretch_is_boxed_without_the_start_or_waypoints(self):
        box = steering.busiest_stretch(route(BASE, [NW, NE]))
        self.assertIsNotNone(box)
        s, w, n, e = box
        self.assertTrue(s < 52.018 and n > 52.024 and w < 13.0 < e)
        self.assertFalse(s <= START.lat <= n)
        self.assertFalse(s <= NW.lat <= n)

    def test_the_detour_apex_is_on_the_quiet_road(self):
        apex = steering.detour_apex(BASE, CALM)
        self.assertAlmostEqual(apex.lng, QUIET_LNG, places=3)

    def test_no_apex_when_the_detour_is_the_same_road(self):
        self.assertIsNone(steering.detour_apex(BASE, BASE))

    def test_the_waypoint_goes_in_driving_order_and_google_gets_three(self):
        apex = Coord(lat=52.02, lng=QUIET_LNG)
        self.assertEqual(steering.with_waypoint([NW, NE], CALM, apex), [apex, NW, NE])
        mid = Coord(lat=52.04, lng=13.015)
        three = steering.with_waypoint([Coord(lat=52.0, lng=QUIET_LNG), mid, NE], CALM, apex)
        self.assertEqual(len(three), steering.MAX_WAYPOINTS)
        self.assertIn(apex, three)


class NearTheStartTests(_Base):
    # The same bumps, but in the parent's own street: nothing to steer round.
    bumps = [[52.001, 13.0, "hump"], [52.002, 13.0, "hump"], [52.003, 13.0, "hump"], [52.004, 13.0, "hump"]]

    def test_stops_by_the_start_are_left_alone(self):
        self.assertIsNone(steering.busiest_stretch(route(BASE, [NW, NE])))


class SteeringTests(_Base):
    def test_a_calmer_drive_is_built_from_plain_waypoints(self):
        r = FakeRouter()
        got = self.steer(r, [route(BASE, [NW, NE])])
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0].steered)
        self.assertEqual(len(r.avoided), 1)
        # The drive offered was routed from waypoints alone, one on the
        # quiet road: what Google Maps will be handed.
        self.assertEqual(got[0].anchors, r.routed[-1])
        self.assertTrue(any(abs(a.lng - QUIET_LNG) < 0.002 for a in got[0].anchors))
        self.assertLess(steering.stop_weight(got[0]), steering.stop_weight(route(BASE, [NW, NE])))

    def test_a_drive_that_goes_back_through_the_stops_is_not_kept(self):
        self.assertEqual(self.steer(FakeRouter(stubborn=True), [route(BASE, [NW, NE])]), [])

    def test_a_calmer_drive_with_an_extra_turn_around_is_not_kept(self):
        r = FakeRouter()
        r.evaluate = lambda *a: _async(route(CALM, a[2], uturn=True))
        self.assertEqual(self.steer(r, [route(BASE, [NW, NE])]), [])

    def test_the_loop_is_pulled_in_to_pay_for_a_long_detour(self):
        self.assertEqual(steering._pull_in(30, 30.5), 1.0)
        self.assertLess(steering._pull_in(30, 40), 1.0)
        self.assertGreaterEqual(steering._pull_in(30, 200), 0.5)

    def test_simulated_routing_is_not_steered(self):
        self.assertEqual(self.steer(MockRouter(), [route(BASE, [NW, NE])]), [])


async def _async(value):
    return value


class TomTomAvoidTests(unittest.TestCase):
    def test_the_avoid_area_goes_in_a_post_body(self):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"routes": [{
                "summary": {"travelTimeInSeconds": 1860, "lengthInMeters": 13000},
                "legs": [{"points": [{"latitude": p.lat, "longitude": p.lng} for p in CALM]}],
                "guidance": {"instructions": []}}]})

        r = R.TomTomRouter("tt-test", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        ev = asyncio.run(r.evaluate_avoiding(START, START, [NW, NE], "quiet", [(52.01, 12.995, 52.03, 13.005)]))
        self.assertEqual(ev.minutes, 31.0)
        self.assertEqual(seen[0].method, "POST")
        rect = json.loads(seen[0].read())["avoidAreas"]["rectangles"][0]
        self.assertEqual(rect["southWestCorner"], {"latitude": 52.01, "longitude": 12.995})
        self.assertEqual(rect["northEastCorner"], {"latitude": 52.03, "longitude": 13.005})
        self.assertIn("traffic=true", str(seen[0].url))


if __name__ == "__main__":
    unittest.main()

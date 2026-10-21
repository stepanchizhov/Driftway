"""
Pins in the navigation link (core/handoff.py; founder, 21 Oct 2026: Google
drove the motorway between a drive's points, "we need to use all the
checkpoints we have if needed"). No network: fake routers.
"""

import asyncio
import math
import os
import sys
import unittest
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(__file__))

from backend.core import handoff  # noqa: E402
from backend.core.generator import generate_routes  # noqa: E402
from backend.core.models import Coord, Direction, GenerateRequest, RoadProfile  # noqa: E402
from test_route_modes import FAR, POOL, ScaledRouter, _geometry  # noqa: E402


def straight(points, n=40):
    out = []
    for a, b in zip(points, points[1:]):
        out.extend(_geometry(a, b, n))
    return out


def bulging(points, km=1.5, n=40):
    """Each leg bowed out sideways by about `km` in its middle: Driftway's
    quieter roads, away from the straight (fast) line."""
    out = []
    for a, b in zip(points, points[1:]):
        k = math.cos(math.radians(a.lat))
        dx, dy = (b.lng - a.lng) * k, b.lat - a.lat          # degrees, locally square
        length = math.hypot(dx, dy) or 1.0
        side = km / 111.0 / length                            # sideways, to the leg's left
        mid = Coord(lat=(a.lat + b.lat) / 2 + dx * side, lng=(a.lng + b.lng) / 2 - dy * side / k)
        out.extend(_geometry(a, mid, n // 2) + _geometry(mid, b, n // 2))
    return out


def link_waypoints(url):
    raw = (parse_qs(urlparse(url).query).get("waypoints") or [""])[0]
    return [tuple(float(x) for x in w.split(",")) for w in raw.split("|") if w]


class FarthestTests(unittest.TestCase):
    def test_the_middle_of_a_detour_is_farthest(self):
        a, b = Coord(lat=51.40, lng=-0.70), Coord(lat=51.40, lng=-0.50)
        ours, theirs = bulging([a, b]), straight([a, b])
        i, off = handoff.farthest_off(ours, theirs)
        self.assertGreater(off, 1300)                          # about the 1.5 km bow
        self.assertLess(abs(i - len(ours) // 2), 4)

    def test_the_same_road_is_not_off(self):
        a, b = Coord(lat=51.40, lng=-0.70), Coord(lat=51.40, lng=-0.50)
        _, off = handoff.farthest_off(straight([a, b]), straight([a, b], n=55))
        self.assertLess(off, handoff.OFF_ROUTE_M)


class BestSetTests(unittest.TestCase):
    def test_a_pin_that_makes_it_worse_is_not_kept(self):
        a, b = Coord(lat=51.40, lng=-0.80), Coord(lat=51.40, lng=-0.40)
        route = bulging([a, b], km=3.0, n=200)
        half = route[: len(route) // 2] + straight([route[len(route) // 2], b], n=100)

        class Guess:
            def __init__(self, geometry):
                self.geometry = geometry

        class Router:
            async def evaluate_as_navigation(self, start, finish, points, profile="mixed"):
                # no pins: straight (follows little); one pin: half the drive;
                # two pins: straight again, as if the second pin sent it astray.
                return Guess({0: straight([a, b]), 1: half}.get(len(points), straight([a, b])))

        points = asyncio.run(handoff.link_points(Router(), a, b, route, []))
        self.assertEqual(len(points), 1)


class SwapTests(unittest.TestCase):
    def test_a_full_link_that_strays_swaps_a_point_for_a_pin(self):
        a = Coord(lat=51.40, lng=-0.80)
        # A loop: out east along the south, a long bow north, back west.
        route = straight([a, Coord(lat=51.40, lng=-0.60)], n=60) + bulging(
            [Coord(lat=51.40, lng=-0.60), Coord(lat=51.40, lng=-0.40)], km=3.0, n=120) +             straight([Coord(lat=51.40, lng=-0.40), Coord(lat=51.37, lng=-0.60), a], n=60)
        anchors = [Coord(lat=51.40, lng=-0.70), Coord(lat=51.40, lng=-0.60), Coord(lat=51.37, lng=-0.60)]

        class Guess:
            def __init__(self, geometry):
                self.geometry = geometry

        class Router:
            # Straight across the bow, unless a point holds it on the bow.
            async def evaluate_as_navigation(self, start, finish, points, profile="mixed"):
                on_bow = any(p.lat > 51.41 for p in points)
                return Guess(route if on_bow else straight([a, Coord(lat=51.40, lng=-0.40),
                                                            Coord(lat=51.37, lng=-0.60), a], n=120))

        points = asyncio.run(handoff.link_points(Router(), a, a, route, anchors))
        self.assertEqual(len(points), handoff.LINK_MAX)
        self.assertTrue(any(p.lat > 51.41 for p in points))          # a pin on the bow
        self.assertNotEqual(points, anchors)


class _Router(ScaledRouter):
    """Driftway's drives bow out between their points; the navigation
    stand-in goes straight through whatever points it's given."""

    name = "test-handoff"

    def __init__(self, same=False):
        super().__init__(direct_minutes=25.0)
        self.same = same
        self.asked = 0

    async def evaluate(self, start, finish, anchors, profile):
        ev = await super().evaluate(start, finish, anchors, profile)
        ev.geometry = bulging([start, *anchors, finish])
        return ev

    async def evaluate_as_navigation(self, start, finish, points, profile="mixed"):
        self.asked += 1
        ev = await super().evaluate(start, finish, points, profile)
        ev.geometry = bulging([start, *points, finish]) if self.same else straight([start, *points, finish])
        return ev


def _req():
    return GenerateRequest(start=POOL, finish=FAR, target_minutes=45, tolerance_minutes=10,
                           road_profile=RoadProfile.QUIET, direction=Direction.SURPRISE)


class LinkTests(unittest.TestCase):
    def test_spare_points_hold_the_drive_to_its_roads(self):
        router = _Router()
        res = asyncio.run(generate_routes(_req(), router))
        self.assertTrue(res.routes)
        for r in res.routes:
            link = link_waypoints(r.maps_url)
            self.assertEqual(len(link), handoff.LINK_MAX)              # every point used
            self.assertGreater(len(link), len(r.waypoints))            # pins beyond the anchors
            for w in r.waypoints:                                       # the anchors are all still there
                self.assertTrue(any(abs(w.lat - p[0]) < 1e-5 and abs(w.lng - p[1]) < 1e-5 for p in link))
            # In driving order: each point further along the drive than the last.
            along = [handoff._position(Coord(lat=p[0], lng=p[1]), r.geometry) for p in link]
            self.assertEqual(along, sorted(along))
        self.assertGreater(router.asked, 0)

    def test_a_drive_the_app_would_follow_anyway_gets_no_pins(self):
        res = asyncio.run(generate_routes(_req(), _Router(same=True)))
        for r in res.routes:
            self.assertEqual(len(link_waypoints(r.maps_url)), len(r.waypoints))

    def test_without_a_stand_in_the_link_is_the_anchors(self):
        res = asyncio.run(generate_routes(_req(), ScaledRouter(direct_minutes=25.0)))
        for r in res.routes:
            self.assertEqual(len(link_waypoints(r.maps_url)), len(r.waypoints))


class TomTomTests(unittest.TestCase):
    def test_the_stand_in_avoids_nothing(self):
        import httpx
        import test_identity_auth0  # noqa: F401  (puts backend/ on the path)
        from core import router as R
        seen = []

        def handler(request):
            seen.append(request.url.params)
            return httpx.Response(200, json={"routes": [{"summary": {"travelTimeInSeconds": 600,
                                                                     "lengthInMeters": 9000}, "legs": []}]})
        R._tomtom_down_until = 0.0
        tt = R.TomTomRouter("tt", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        asyncio.run(tt.evaluate_as_navigation(POOL, FAR, [Coord(lat=51.5, lng=-0.66)], "quiet"))
        self.assertEqual(seen[0].get_list("avoid"), [])
        self.assertEqual(seen[0].get("routeType"), "fastest")


if __name__ == "__main__":
    unittest.main()

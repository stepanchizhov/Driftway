"""
Ferries (founder, 18 Oct 2026: testers driving from Woking to the Isle of
Wight). A drive Driftway shapes never takes a ferry; a direct way that needs
one gets a way on land if there is one, otherwise the quickest way, saying
to plan to the terminal. No network: fake TomTom and openrouteservice.
"""

import asyncio
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import httpx  # noqa: E402

import test_identity_auth0  # noqa: E402,F401  (puts backend/ on the path)

from core import ors, router as R  # noqa: E402
from core.models import Coord  # noqa: E402
# The generator's tests share test_route_modes' routers, imported as backend.*.
from backend.core.generator import FERRY_NOTICE, generate_routes  # noqa: E402
from backend.core.models import Direction, GenerateRequest, RoadProfile  # noqa: E402
from backend.core.router import EvaluatedRoute  # noqa: E402
from test_route_modes import FAR, MIX, POOL, ScaledRouter, _geometry  # noqa: E402

HOME = Coord(lat=51.3190, lng=-0.5580)          # Woking, roughly
PORT = Coord(lat=50.7930, lng=-1.1080)          # Portsmouth, roughly
ISLAND = Coord(lat=50.7000, lng=-1.2900)        # the Isle of Wight, roughly


def tomtom_body(ferry=False):
    route = {"summary": {"travelTimeInSeconds": 5400, "lengthInMeters": 90000},
             "legs": [{"points": [{"latitude": 51.3, "longitude": -0.55},
                                  {"latitude": 50.7, "longitude": -1.29}]}]}
    if ferry:
        route["sections"] = [{"startPointIndex": 0, "endPointIndex": 1, "sectionType": "FERRY"}]
    return {"routes": [route]}


class TomTomTests(unittest.TestCase):
    def setUp(self):
        R._tomtom_down_until = 0.0

    def _run(self, call, ferry=False):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json=tomtom_body(ferry))
        router = R.TomTomRouter("tt", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        ev = asyncio.run(call(router))
        return ev, seen[0].url.params

    def test_a_shaped_drive_avoids_ferries_and_the_direct_way_may_take_one(self):
        _, loop = self._run(lambda r: r.evaluate(HOME, HOME, [PORT], "mixed"))
        self.assertIn("ferries", loop.get_list("avoid"))
        self.assertIn("alreadyUsedRoads", loop.get_list("avoid"))
        _, direct = self._run(lambda r: r.evaluate(HOME, ISLAND, [], "mixed"))
        self.assertNotIn("ferries", direct.get_list("avoid"))
        self.assertEqual(direct.get("sectionType"), "ferry")
        _, dry = self._run(lambda r: r.evaluate_without_ferries(HOME, ISLAND, [], "mixed"))
        self.assertIn("ferries", dry.get_list("avoid"))

    def test_a_crossing_is_noticed(self):
        ev, _ = self._run(lambda r: r.evaluate(HOME, ISLAND, [], "mixed"), ferry=True)
        self.assertTrue(ev.ferry)
        ev, _ = self._run(lambda r: r.evaluate(HOME, PORT, [], "mixed"))
        self.assertFalse(ev.ferry)

    def test_no_route_is_asked_once(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(400, json={"error": {"description": "NO_ROUTE_FOUND"}})
        router = R.TomTomRouter("tt", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        self.assertIsNone(asyncio.run(router.evaluate_without_ferries(HOME, ISLAND, [], "mixed")))
        self.assertEqual(len(calls), 1)
        self.assertTrue(R.tomtom_available())          # an answer, not an outage


class OrsTests(unittest.TestCase):
    def setUp(self):
        ors.reset_budgets()
        self.env = mock.patch.dict(os.environ, {"ORS_API_KEY": "ors-test"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_ferries_avoided_on_shaped_drives_and_noticed_on_the_direct_way(self):
        seen = []

        def handler(request):
            seen.append(json.loads(request.read()))
            return httpx.Response(200, json={"features": [{
                "geometry": {"coordinates": [[-0.55, 51.3], [-1.29, 50.7]]},
                "properties": {"summary": {"duration": 5400, "distance": 90000}, "segments": [],
                               "extras": {"waytypes": {"summary": [{"value": 3, "distance": 80000},
                                                                   {"value": 9, "distance": 10000}]}}}}]})
        router = R.ORSRouter(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        asyncio.run(router.evaluate(HOME, HOME, [PORT], "mixed"))
        self.assertEqual(seen[-1]["options"]["avoid_features"], ["ferries"])
        ev = asyncio.run(router.evaluate(HOME, ISLAND, [], "mixed"))
        self.assertNotIn("options", seen[-1])
        self.assertEqual(seen[-1]["extra_info"], ["waytype"])
        self.assertTrue(ev.ferry)


class _FerryRouter(ScaledRouter):
    """The direct way crosses water; with `land`, there is also one on land."""

    name = "test-ferry"

    def __init__(self, land=None):
        super().__init__(direct_minutes=25.0)
        self.land = land

    async def evaluate(self, start, finish, anchors, profile):
        ev = await super().evaluate(start, finish, anchors, profile)
        if not anchors:
            ev.ferry = True
        return ev

    async def evaluate_without_ferries(self, start, finish, anchors, profile):
        if self.land is None:
            return None
        return EvaluatedRoute(anchors=[], minutes=self.land, distance_km=20.0, road_mix=MIX,
                              geometry=_geometry(start, finish))


def _req(minutes=45):
    return GenerateRequest(start=POOL, finish=FAR, target_minutes=minutes, tolerance_minutes=10,
                           road_profile=RoadProfile.MIXED, direction=Direction.SURPRISE)


class GeneratorTests(unittest.TestCase):
    def test_across_the_water_the_quickest_way_and_plan_to_the_terminal(self):
        res = asyncio.run(generate_routes(_req(), _FerryRouter()))
        self.assertEqual(len(res.routes), 1)
        self.assertTrue(res.routes[0].is_direct)
        self.assertEqual(res.notice, FERRY_NOTICE)
        self.assertIn("ferry", res.routes[0].caveat)

    def test_a_shaped_drive_that_comes_back_on_a_ferry_is_never_offered(self):
        class SomeOnFerries(ScaledRouter):
            async def evaluate(self, start, finish, anchors, profile):
                ev = await super().evaluate(start, finish, anchors, profile)
                if anchors and anchors[0].lat > start.lat:     # north-bound shapes cross water
                    ev.ferry = True
                return ev
        res = asyncio.run(generate_routes(_req(), SomeOnFerries(direct_minutes=25.0)))
        self.assertTrue(res.routes)
        self.assertFalse(any(r.is_direct for r in res.routes))          # a drive, not the fallback
        self.assertTrue(all(r.waypoints and r.waypoints[0].lat <= POOL.lat for r in res.routes))

    def test_when_every_drive_needs_a_ferry_the_direct_way_is_offered(self):
        class AllOnFerries(ScaledRouter):
            async def evaluate(self, start, finish, anchors, profile):
                ev = await super().evaluate(start, finish, anchors, profile)
                ev.ferry = bool(anchors)
                return ev
        res = asyncio.run(generate_routes(_req(), AllOnFerries(direct_minutes=25.0)))
        self.assertEqual([r.is_direct for r in res.routes], [True])

    def test_with_a_way_on_land_the_drive_is_planned_as_usual(self):
        res = asyncio.run(generate_routes(_req(), _FerryRouter(land=28.0)))
        self.assertNotEqual(res.notice, FERRY_NOTICE)
        self.assertTrue(res.routes)
        self.assertFalse(any(r.is_direct for r in res.routes))
        self.assertEqual(res.direct_minutes, 28.0)            # the way on land


if __name__ == "__main__":
    unittest.main()

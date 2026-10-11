"""
Routes of your own (founder request, 11 Oct 2026): points in the order
walked - drawn, from a GPX file, or a made walk saved - followed along mapped
ways with the profile's rules and judged like any other walk.
"""

import asyncio
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import httpx  # noqa: E402

from test_identity_auth0 import _fresh  # noqa: E402
from test_walk_generation import feature  # noqa: E402

LOOP = [(52.0, 13.0), (52.0045, 13.0), (52.0045, 13.004), (52.0002, 13.0001)]
ONE_WAY = [(52.0, 13.0), (52.0045, 13.0)]


def ok(seen=None):
    def handler(request):
        if seen is not None:
            seen.append(json.loads(request.read()))
        return httpx.Response(200, json={"type": "FeatureCollection",
                                         "features": [feature()]})
    return handler


class _Base(unittest.TestCase):
    def setUp(self):
        from core import ors
        ors.reset_budgets()
        os.environ["ORS_API_KEY"] = "test-key"

    def tearDown(self):
        os.environ.pop("ORS_API_KEY", None)

    def trace(self, handler, points=LOOP, profile="walker"):
        from core.walking import generate as gen
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return asyncio.run(gen.trace_walk(points, profile, "My Long Walk", "Home",
                                          client=client))


class RequestTests(_Base):
    def test_every_point_goes_in_order_as_lng_lat_with_a_snap_radius(self):
        from core.walking import generate as gen
        seen = []
        self.trace(ok(seen))
        self.assertEqual(len(seen), 1)                          # one call
        self.assertEqual(seen[0]["coordinates"], [[p[1], p[0]] for p in LOOP])
        self.assertEqual(seen[0]["radiuses"], [gen.TRACE_SNAP_M] * len(LOOP))
        self.assertNotIn("round_trip", seen[0]["options"])

    def test_a_pram_keeps_its_rules(self):
        seen = []
        route = self.trace(ok(seen), profile="pram")
        self.assertEqual(seen[0]["options"].get("avoid_features"), ["steps"])
        self.assertTrue(any("isn't suitable for a pram" in n for n in route.notes))

    def test_a_closed_route_is_a_loop_and_an_open_one_there_and_back(self):
        self.assertEqual(self.trace(ok()).shape, "loop")
        self.assertEqual(self.trace(ok(), points=ONE_WAY).shape, "out_and_back")

    def test_it_says_what_it_is(self):
        route = self.trace(ok())
        self.assertEqual(route.name, "My Long Walk")
        self.assertIn("Your own route", route.summary)
        self.assertFalse(any(n.startswith("Generated just now") for n in route.notes))


class FailureTests(_Base):
    def test_a_point_far_from_any_path_is_named(self):
        from core.walking import generate as gen

        def handler(request):
            return httpx.Response(404, json={"error": {"code": 2010, "message":
                "Could not find routable point within a radius of 100.0 meters of "
                "specified coordinate 2: 13.0040000 52.0045000."}})
        with self.assertRaises(gen.TraceProblem) as cm:
            self.trace(handler)
        self.assertEqual(cm.exception.point, 3)
        self.assertIn("Point 3", str(cm.exception))
        self.assertNotIn("52.0045", str(cm.exception))         # no coordinates echoed

    def test_the_provider_refusing_is_not_blamed_on_the_route(self):
        from core.walking import generate as gen

        def handler(request):
            return httpx.Response(403, json={"error": "Quota exceeded"})
        with self.assertRaises(gen.ProviderRefused):
            self.trace(handler)

    def test_one_point_is_not_a_route(self):
        from core.walking import generate as gen
        with self.assertRaises(gen.TraceProblem):
            self.trace(ok(), points=LOOP[:1])


class EndpointTests(unittest.TestCase):
    def setUp(self):
        os.environ["WALKING_ENABLED"] = "true"
        self.client, _ = _fresh()
        from core import ors
        ors.reset_budgets()

    def tearDown(self):
        self.client.close()
        for k in ("WALKING_ENABLED", "ORS_API_KEY"):
            os.environ.pop(k, None)

    def post(self, **extra):
        os.environ["ORS_API_KEY"] = "test-key"
        real = httpx.AsyncClient
        body = {"profile": "walker", "minutes": 30,
                "points": [{"lat": a, "lng": b} for a, b in LOOP], **extra}
        with mock.patch("core.walking.generate.httpx.AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(ok()))):
            return self.client.post("/api/walks/trace", json=body)

    def test_your_route_comes_back_judged(self):
        r = self.post(name="My Long Walk")
        self.assertEqual(r.status_code, 200, r.text)
        walk = r.json()["walks"][0]
        self.assertEqual(walk["name"], "My Long Walk")
        self.assertIn("verdict", walk)
        self.assertIn("openrouteservice", r.json()["attribution"])

    def test_at_your_pace(self):
        slow = self.post(pace_kmh=3).json()["walks"][0]
        fast = self.post(pace_kmh=6).json()["walks"][0]
        self.assertLess(fast["fit"]["full_minutes"], slow["fit"]["full_minutes"])

    def test_too_many_or_too_few_points_are_refused(self):
        from core.walking import generate as gen
        self.assertEqual(self.post(points=[{"lat": 52, "lng": 13}]).status_code, 422)
        many = [{"lat": 52 + i * 1e-4, "lng": 13} for i in range(gen.MAX_TRACE_POINTS + 1)]
        self.assertEqual(self.post(points=many).status_code, 422)

    def test_nothing_is_stored(self):
        from core.db import Base, SessionLocal
        s = SessionLocal()
        count = lambda: {t.name: len(s.execute(t.select()).fetchall())
                         for t in Base.metadata.sorted_tables}
        before = count()
        self.assertEqual(self.post().status_code, 200)
        after = count()
        s.close()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()

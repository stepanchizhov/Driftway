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


class PramTests(_Base):
    """The earlier pram + Greener/Quieter problem cannot come back this way:
    a route of your own is always made with the profile's own routing."""

    def urls_for(self, profile):
        urls = []

        def handler(request):
            urls.append(str(request.url))
            return ok()(request)
        self.trace(handler, profile=profile)
        return urls

    def test_a_pram_route_uses_wheelchair_routing(self):
        urls = self.urls_for("pram")
        self.assertTrue(urls and all("/wheelchair/" in u for u in urls))

    def test_walking_profiles_use_walking_routing(self):
        for profile in ("carrier", "walker"):
            urls = self.urls_for(profile)
            self.assertTrue(urls and all("/foot-walking/" in u for u in urls), profile)


class FidelityTests(unittest.TestCase):
    """Founder brief, 11 Oct: say where the walk shown differs from the
    parent's own route; never imply the track was kept exactly."""

    # A synthetic loop with a narrow connector: north 450 m, east 270 m along
    # a short connector, back south. Nobody's address.
    LOOP = [(52.0, 13.0), (52.002, 13.0), (52.004, 13.0), (52.004, 13.002),
            (52.004, 13.004), (52.002, 13.004), (52.0, 13.004), (52.0, 13.002),
            (52.0, 13.0)]

    def route(self, coords):
        from core.walking import generate as gen
        feat = {"type": "Feature",
                "geometry": {"type": "LineString",
                             "coordinates": [[lng, lat, 30] for lat, lng in coords]},
                "properties": {"extras": {}}}
        return gen.route_from_ors(feat, walk_id="m", name="m", start_label="m")

    def test_a_route_that_follows_the_points_is_not_flagged(self):
        from core.walking import generate as gen
        f = gen.trace_fidelity(self.LOOP, self.route(self.LOOP))
        self.assertFalse(f["changed"])
        self.assertEqual(f["far_points"], [])
        self.assertLess(f["max_offset_m"], 1)

    def test_a_parallel_path_is_flagged_with_the_points_it_misses(self):
        """Routed along a parallel path 150 m east of the parent's north leg."""
        from core.walking import generate as gen
        east = [(lat, lng + 0.0022) if lng == 13.0 and 0 < lat - 52.0 < 0.004 else (lat, lng)
                for lat, lng in self.LOOP]
        f = gen.trace_fidelity(self.LOOP, self.route(east))
        self.assertTrue(f["changed"])
        self.assertIn(2, f["far_points"])
        self.assertGreater(f["max_offset_m"], gen.TRACE_FAR_M)

    def test_a_long_way_round_is_flagged(self):
        from core.walking import generate as gen
        detour = (self.LOOP[:3] + [(52.004, 12.99), (52.012, 12.99), (52.012, 13.004)]
                  + self.LOOP[4:])
        f = gen.trace_fidelity(self.LOOP, self.route(detour))
        self.assertTrue(f["changed"])
        self.assertGreater(f["longer_share"], gen.TRACE_LONGER_SHARE)

    def test_thinning_keeps_a_narrow_connector(self):
        """A dense GPX-like track (1,600 points) thinned evenly to 40, as the
        app does, still has points on the 270 m connector, and the full line
        through them is not flagged."""
        from core.walking import generate as gen
        dense = []
        for a, b in zip(self.LOOP, self.LOOP[1:]):
            for k in range(200):
                dense.append((a[0] + (b[0] - a[0]) * k / 200, a[1] + (b[1] - a[1]) * k / 200))
        dense.append(self.LOOP[-1])
        step = (len(dense) - 1) / 39
        thinned = [dense[round(i * step)] for i in range(40)]
        connector = [p for p in thinned if abs(p[0] - 52.004) < 1e-9 and 13.0 < p[1] < 13.004]
        self.assertGreaterEqual(len(connector), 2)
        f = gen.trace_fidelity(thinned, self.route(dense))
        self.assertFalse(f["changed"])


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

    def test_the_response_says_how_far_the_walk_strays(self):
        trace = self.post().json()["trace"]
        self.assertEqual(set(trace), {"source_m", "routed_m", "max_offset_m",
                                      "far_points", "longer_share", "changed"})

    def test_figures_come_from_the_geometry_shown_at_the_pace_chosen(self):
        from core.walking.generate import _haversine
        walk = self.post(pace_kmh=5).json()["walks"][0]
        out = [s for s in walk["sections"]
               if walk["shape"] != "out_and_back" or s["to_m"] <= walk["distance_m"] / 2 + 1]
        drawn = sum(_haversine(a, b) for s in out
                    for a, b in zip(s["geometry"], s["geometry"][1:]))
        whole = drawn * (2 if walk["shape"] == "out_and_back" else 1)
        self.assertAlmostEqual(walk["distance_m"], whole, delta=max(5, whole * 0.01))
        climb = walk["ascent_m"] or 0
        expected = walk["distance_m"] / 1000 / 5 * 60 + climb / 10
        self.assertAlmostEqual(walk["fit"]["full_minutes"], expected, delta=1)

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

"""
Walks when openrouteservice struggles (founder, 13 Oct 2026: walks failed
all afternoon, "This happens too often. We need a proper fallback and
messaging towards the user").

  * a walk call that times out or fails on the provider's side marks that
    kind of walk as struggling: later walks don't wait for it;
  * walks other than pram walks are then made with TomTom's walking routes,
    and say that surfaces, steps and slopes aren't known;
  * pram walks never use the stand-in (it can't keep a pram's rules): the
    parent is told plainly what is wrong and what still works.

No network: both providers are answered by mock transports.
"""

import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import httpx  # noqa: E402

from test_walk_generation import BODY, EndpointTests, feature  # noqa: E402

#: The real client class: the tests patch httpx.AsyncClient itself.
REAL_CLIENT = httpx.AsyncClient


def gen():
    import importlib
    return importlib.import_module("core.walking.generate")


def tomtom_route(n=30):
    """A TomTom walking route: a square loop of about 2.4 km near 52.0 N."""
    pts = ([(52.0 + i * 0.0002, 13.0) for i in range(n)]
           + [(52.0 + n * 0.0002, 13.0 + i * 0.0003) for i in range(n)]
           + [(52.0 + (n - i) * 0.0002, 13.0 + n * 0.0003) for i in range(n)]
           + [(52.0, 13.0 + (n - i) * 0.0003) for i in range(n + 1)])
    return {"routes": [{"summary": {"lengthInMeters": 2400, "travelTimeInSeconds": 1800},
                        "legs": [{"points": [{"latitude": a, "longitude": b} for a, b in pts]}]}]}


class _Clean(unittest.TestCase):
    def setUp(self):
        from core import ors
        ors.reset_budgets()
        gen().reset_health()
        os.environ["ORS_API_KEY"] = "test-key"
        os.environ["TOMTOM_API_KEY"] = "tt-test"

    def tearDown(self):
        gen().reset_health()
        for k in ("ORS_API_KEY", "TOMTOM_API_KEY"):
            os.environ.pop(k, None)


def timing_out(seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        raise httpx.ReadTimeout("slow", request=request)
    return REAL_CLIENT(transport=httpx.MockTransport(handler))


def tomtom_client(seen):
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=tomtom_route())
    return REAL_CLIENT(transport=httpx.MockTransport(handler))


class HealthTests(_Clean):
    def test_a_timeout_marks_the_kind_of_walk_as_struggling_and_later_walks_dont_wait(self):
        g = gen()
        seen = []
        with self.assertRaises(g.ProviderSlow):
            asyncio.run(g._post(timing_out(seen), "foot-walking", {}))
        self.assertTrue(g._struggling)
        # The next call is refused at once, without a request.
        n = len(seen)
        with self.assertRaises(g.ProviderSlow):
            asyncio.run(g._post(timing_out(seen), "foot-walking", {}))
        self.assertEqual(len(seen), n)

    def test_another_kind_of_walk_is_not_affected(self):
        g = gen()
        g._note("foot-walking", False)
        self.assertTrue(g.struggling("foot-walking"))
        self.assertFalse(g.struggling("wheelchair"))

    def test_a_good_answer_clears_it(self):
        g = gen()
        g._note("foot-walking", False)
        g._note("foot-walking", True)
        self.assertFalse(g.struggling("foot-walking"))


class StandInTests(_Clean):
    def run_generate(self, profile):
        g = gen()
        tt = []
        with mock.patch("core.walking.tomtom_walk._client", lambda: tomtom_client(tt)):
            routes = asyncio.run(g.generate((52.0, 13.0), profile, 30, "Your location", timing_out()))
        return routes, tt

    def test_a_carrier_walk_comes_from_tomtom_and_says_what_it_cannot_know(self):
        routes, tt = self.run_generate("carrier")
        self.assertTrue(routes)
        self.assertEqual(routes[0].sources[0]["id"], "tomtom")
        self.assertTrue(any("surfaces, steps, slopes and gates aren't known" in n for n in routes[0].notes))
        # Walking, not driving; no heights, so no slopes claimed.
        self.assertTrue(tt)
        self.assertTrue(all("travelMode=pedestrian" in str(r.url) for r in tt))
        self.assertTrue(all(s.gradient is None for s in routes[0].sections))
        # The time leaves the climb out, and says so; nothing reassures.
        from core.walking.catalogue import assess_route
        from core.walking.profiles import CarrierSetup
        w = assess_route(routes[0], "carrier", CarrierSetup(), 30, False)
        self.assertIn("the climb isn't known", w["assumptions"])
        self.assertIsNone(w["ascent_m"])
        self.assertEqual(w["coverage"]["surface_known_share"], 0)
        self.assertNotEqual(w["verdict"], "ok")

    def test_a_pram_walk_never_uses_the_stand_in(self):
        g = gen()
        with self.assertRaises(g.ProviderSlow) as caught:
            self.run_generate("pram")
        self.assertIn("pram-friendly routing", str(caught.exception))

    def test_without_tomtom_it_says_what_is_wrong(self):
        os.environ.pop("TOMTOM_API_KEY", None)
        g = gen()
        with self.assertRaises(g.ProviderSlow) as caught:
            asyncio.run(g.generate((52.0, 13.0), "walker", 30, "x", timing_out()))
        self.assertIn("not your phone or connection", str(caught.exception))


class StandInEndpointTests(EndpointTests):
    """The same endpoint, with openrouteservice timing out."""

    def setUp(self):
        super().setUp()
        gen().reset_health()

    def tearDown(self):
        gen().reset_health()
        os.environ.pop("TOMTOM_API_KEY", None)
        super().tearDown()

    def _slow_ors(self):
        os.environ["ORS_API_KEY"] = "test-key"
        return mock.patch("core.walking.generate.httpx.AsyncClient", lambda **kw: timing_out())

    def test_a_pram_parent_is_told_what_is_wrong_and_what_still_works(self):
        with self._slow_ors():
            r = self.client.post("/api/walks/generate", json=BODY, headers=self.auth)
        self.assertEqual(r.status_code, 503)
        d = r.json()["detail"]
        self.assertEqual(d["code"], "provider_slow")
        self.assertIn("still work", d["message"])
        self.assertEqual(d["retry_after_s"], 60)

    def test_a_carrier_walk_from_the_stand_in_says_so(self):
        os.environ["TOMTOM_API_KEY"] = "tt-test"
        tt = []
        with self._slow_ors(), mock.patch("core.walking.tomtom_walk._client", lambda: tomtom_client(tt)):
            r = self.client.post("/api/walks/generate", json={**BODY, "profile": "carrier"},
                                 headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        out = r.json()
        self.assertEqual(out["provider"], "tomtom")
        self.assertIn("TomTom", out["attribution"])
        self.assertIn("struggling", out["notice"])

    # The inherited tests run here too, with openrouteservice answering.


class CheckpointAndOwnRouteTests(_Clean):
    """14 Oct 2026: walks via checkpoints and routes of your own too."""

    def test_a_walk_via_a_checkpoint_comes_from_tomtom(self):
        g = gen()
        tt = []
        with mock.patch("core.walking.tomtom_walk._client", lambda: tomtom_client(tt)):
            routes = asyncio.run(g.via_walk((52.0, 13.0), [(52.004, 13.003)], "carrier", "Start", "The oak",
                                            client=timing_out(), minutes=45))
        self.assertTrue(routes)
        self.assertEqual(routes[0].sources[0]["id"], "tomtom")
        self.assertEqual(routes[0].via["label"], "The oak")
        # Start, checkpoint, back: one request per variant, walking, no road twice.
        self.assertTrue(all("travelMode=pedestrian" in str(r.url) and "alreadyUsedRoads" in str(r.url) for r in tt))
        # The same loop three times over is one walk.
        self.assertEqual(len(routes), 1)

    def test_a_pram_walk_via_a_checkpoint_is_told_plainly(self):
        g = gen()
        with self.assertRaises(g.ProviderSlow) as caught:
            asyncio.run(g.via_walk((52.0, 13.0), [(52.004, 13.003)], "pram", "Start", "The oak",
                                   client=timing_out(), minutes=45))
        self.assertIn("pram-friendly routing", str(caught.exception))

    def test_a_route_of_your_own_comes_from_tomtom_through_your_points(self):
        g = gen()
        tt = []
        pts = [(52.0, 13.0), (52.003, 13.004), (52.0, 13.0)]
        with mock.patch("core.walking.tomtom_walk._client", lambda: tomtom_client(tt)):
            route = asyncio.run(g.trace_walk(pts, "walker", "Mine", "Start", client=timing_out()))
        self.assertEqual(route.sources[0]["id"], "tomtom")
        self.assertEqual(route.shape, "loop")
        self.assertEqual(len(tt), 1)
        # Your own route may walk a road twice: no "avoid" asked.
        self.assertNotIn("alreadyUsedRoads", str(tt[0].url))


class TomTomWalkTests(_Clean):
    def test_a_loop_far_off_its_length_is_asked_for_again(self):
        from core.walking import tomtom_walk
        seen = []
        asyncio.run(tomtom_walk.loops((52.0, 13.0), 6000, tomtom_client(seen)))
        # Three loops, each 2.4 km against 6 km asked: each asked again, larger.
        self.assertEqual(len(seen), 6)

    def test_the_ors_shaped_feature_has_no_heights(self):
        from core.walking import tomtom_walk
        f = tomtom_walk._feature(tomtom_route()["routes"][0])
        self.assertEqual(len(f["geometry"]["coordinates"][0]), 2)
        self.assertEqual(f["properties"]["summary"]["distance"], 2400)

    def test_the_ors_feature_still_has_heights(self):
        self.assertEqual(len(feature()["geometry"]["coordinates"][0]), 3)


if __name__ == "__main__":
    unittest.main()

"""
Walks generated from any start, via openrouteservice.

No network: openrouteservice responses here are built in the documented shape
(GeoJSON feature, [lng, lat, ele] coordinates, extras as [start, end, code]
ranges). They prove the translation and the gates. They do NOT prove the live
service behaves as documented - that is checked against production once the
key is in place, and recorded separately.
"""

import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import httpx  # noqa: E402

from test_identity_auth0 import ADMIN, _fresh, _token  # noqa: E402

# Six points heading north, ~100 m apart, climbing 1 m then 10 m per step.
COORDS = [[13.0, 52.0 + i * 0.0009, h] for i, h in enumerate([30, 31, 32, 42, 52, 52])]


def feature(surface=None, waytype=None):
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": COORDS},
            "properties": {"extras": {
                "surface": {"values": surface or [[0, 2, 3], [2, 4, 10], [4, 5, 17]]},
                "waytype": {"values": waytype or [[0, 2, 3], [2, 3, 8], [3, 5, 4]]},
            }}}


def ors_transport(status=200, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if status != 200:
            return httpx.Response(status, json={"error": "nope"})
        return httpx.Response(200, json={"type": "FeatureCollection",
                                         "features": [feature()]})
    return httpx.MockTransport(handler)


class TranslationTests(unittest.TestCase):
    def setUp(self):
        from core.walking.generate import route_from_ors
        self.route = route_from_ors(feature(), walk_id="g", name="Loop",
                                    start_label="Your location")

    def test_surface_codes_become_the_same_classes_as_curated_walks(self):
        from core.walking.evidence import Surface
        kinds = [s.surface for s in self.route.sections]
        self.assertEqual(kinds[0], Surface.SEALED)          # 3 = asphalt
        self.assertIn(Surface.LOOSE, kinds)                 # 10 = gravel
        self.assertEqual(kinds[-1], Surface.SOFT)           # 17 = grass

    def test_steps_in_the_way_type_become_a_barrier(self):
        kinds = [b.kind.value for s in self.route.sections for b in s.barriers]
        self.assertEqual(kinds, ["steps"])

    def test_heights_become_gradients(self):
        steepest = max(s.gradient.steepest_up_pct for s in self.route.sections)
        self.assertGreater(steepest, 5)

    def test_the_walk_says_what_it_cannot_know(self):
        self.assertTrue(any("Gates, stiles" in n for n in self.route.notes))
        self.assertEqual(self.route.sources[0]["licence"], "CC-BY-SA 4.0")

    def test_a_pram_walk_is_judged_by_the_same_rules(self):
        from core.walking.catalogue import assess_route
        from core.walking.profiles import PramSetup
        card = assess_route(self.route, "pram", PramSetup())
        self.assertEqual(card["verdict"], "blocked")        # the steps


class RequestTests(unittest.TestCase):
    def test_a_pram_asks_for_wheelchair_routing_without_steps(self):
        from core.walking.generate import request_body
        profile, body = request_body((52.0, 13.0), "pram", 60, 1)
        self.assertEqual(profile, "wheelchair")
        self.assertEqual(body["options"]["avoid_features"], ["steps"])
        self.assertEqual(body["coordinates"], [[13.0, 52.0]])   # lng, lat
        self.assertEqual(body["options"]["round_trip"]["length"], 4000)

    def test_a_carrier_walks_and_steps_are_allowed(self):
        from core.walking.generate import request_body
        profile, body = request_body((52.0, 13.0), "carrier", 30, 2)
        self.assertEqual(profile, "foot-walking")
        self.assertNotIn("avoid_features", body["options"])

    def test_nothing_but_the_start_point_is_sent(self):
        """The provider's terms forbid sending personal data."""
        from core.walking import generate as gen
        seen = []
        os.environ["ORS_API_KEY"] = "test-key"
        try:
            client = httpx.AsyncClient(transport=ors_transport(seen=seen))
            asyncio.run(gen.generate((52.0, 13.0), "carrier", 30, "Your location", client))
        finally:
            os.environ.pop("ORS_API_KEY", None)
        body = seen[0].content.decode()
        self.assertNotIn("Your location", body)
        self.assertEqual(len(seen), 3)

    def test_a_provider_failure_is_reported_not_papered_over(self):
        from core.walking import generate as gen
        os.environ["ORS_API_KEY"] = "test-key"
        try:
            client = httpx.AsyncClient(transport=ors_transport(status=500))
            with self.assertRaises(gen.GenerationUnavailable):
                asyncio.run(gen.generate((52.0, 13.0), "pram", 30, "x", client))
        finally:
            os.environ.pop("ORS_API_KEY", None)


BODY = {"profile": "pram", "minutes": 30, "start": {"lat": 51.48, "lng": -0.6},
        "start_label": "Your location"}


class EndpointTests(unittest.TestCase):
    def setUp(self):
        os.environ["WALKING_ENABLED"] = "true"
        self.client, _ = _fresh()
        minted = self.client.post("/api/admin/beta-invites",
                                  headers={"X-Admin-Token": ADMIN}).json()
        self.token = _token(sub="auth0|gen")
        self.client.post("/api/auth/accept-beta-invite",
                         json={"invite_token": minted["invite_token"]},
                         headers={"Authorization": f"Bearer {self.token}"})
        self.auth = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        self.client.close()
        for k in ("WALKING_ENABLED", "ORS_API_KEY"):
            os.environ.pop(k, None)

    def _with_ors(self, status=200):
        os.environ["ORS_API_KEY"] = "test-key"
        real = httpx.AsyncClient
        return mock.patch("core.walking.generate.httpx.AsyncClient",
                          lambda **kw: real(transport=ors_transport(status)))

    def test_without_a_key_it_says_it_is_not_switched_on(self):
        r = self.client.post("/api/walks/generate", json=BODY, headers=self.auth)
        self.assertEqual(r.status_code, 503)
        self.assertFalse(self.client.get("/api/health").json()["walk_generation"])

    def test_anonymous_requests_are_refused_before_the_provider_is_called(self):
        with self._with_ors():
            r = self.client.post("/api/walks/generate", json=BODY)
        self.assertEqual(r.status_code, 403)

    def test_an_admitted_account_gets_judged_walks(self):
        with self._with_ors():
            r = self.client.post("/api/walks/generate", json=BODY, headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        walks = r.json()["walks"]
        self.assertEqual(len(walks), 3)
        self.assertTrue(all("verdict" in w and "markers" in w for w in walks))
        self.assertIn("openrouteservice", r.json()["attribution"])

    def test_a_provider_outage_is_a_503_not_an_empty_success(self):
        with self._with_ors(status=502):
            r = self.client.post("/api/walks/generate", json=BODY, headers=self.auth)
        self.assertEqual(r.status_code, 503)

    def test_usage_is_capped_per_caller(self):
        with self._with_ors():
            codes = [self.client.post("/api/walks/generate", json=BODY,
                                      headers=self.auth).status_code for _ in range(6)]
        self.assertIn(429, codes)


class CharacterTests(unittest.TestCase):
    """Greener and quieter walks - founder request, 9 Oct."""

    def test_a_greener_walk_asks_for_the_green_weighting(self):
        from core.walking.generate import request_body
        profile, body = request_body((52.0, 13.0), "carrier", 30, 1, "green")
        self.assertEqual(profile, "foot-walking")
        self.assertEqual(body["options"]["profile_params"],
                         {"weightings": {"green": {"factor": 1.0}}})

    def test_a_pram_wanting_quiet_walks_keeps_steps_avoided(self):
        """Wheelchair routing has no weightings, so walking routing is used."""
        from core.walking.generate import request_body
        profile, body = request_body((52.0, 13.0), "pram", 30, 1, "quiet")
        self.assertEqual(profile, "foot-walking")
        self.assertEqual(body["options"]["avoid_features"], ["steps"])

    def test_no_preference_sends_no_weighting(self):
        from core.walking.generate import request_body
        profile, body = request_body((52.0, 13.0), "pram", 30, 1)
        self.assertEqual(profile, "wheelchair")
        self.assertNotIn("profile_params", body["options"])

    def test_the_share_along_roads_comes_from_the_way_types(self):
        from core.walking.generate import route_from_ors
        r = route_from_ors(feature(), walk_id="g", name="x", start_label="x")
        # Way types: points 0-2 street (3), 2-3 steps, 3-5 path.
        self.assertAlmostEqual(r.road_share, 0.4, places=1)

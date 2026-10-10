"""
Walks generated from any start, via openrouteservice.

No network: openrouteservice responses here are built in the documented shape
(GeoJSON feature, [lng, lat, ele] coordinates, extras as [start, end, code]
ranges). They prove the translation and the gates. They do NOT prove the live
service behaves as documented - that is checked against production once the
key is in place, and recorded separately.
"""

import asyncio
import json
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


class _FreshBudget(unittest.TestCase):
    """The provider call budget is process-wide by design; tests start clean."""

    def setUp(self):
        from core.walking import generate as gen
        gen._CALL_BUDGET = None
        gen._WEIGHT_FORM = None


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


class RequestTests(_FreshBudget):
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
        # A developer's backend/.env may hold a real key (loaded by main.py);
        # this test is about its absence, and must never reach the provider.
        os.environ.pop("ORS_API_KEY", None)
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


class CharacterTests(_FreshBudget):
    """Greener and quieter walks - founder request, 9 Oct."""

    def test_a_greener_walk_asks_for_the_green_weighting(self):
        from core.walking.generate import request_body
        profile, body = request_body((52.0, 13.0), "carrier", 30, 1, "green")
        self.assertEqual(profile, "foot-walking")
        # The integer form: the only one the live API accepted, 10 Oct 2026.
        self.assertEqual(body["options"]["profile_params"], {"weightings": {"green": 1}})
        # ... and the data behind it, so a walk can say when it was flat.
        self.assertIn("green", body["extra_info"])

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


# A straight line north, ~1 km, points every ~100 m.
LINE = [[13.0, 52.0 + i * 0.0009, 30] for i in range(11)]


def line_feature(coords):
    n = len(coords) - 1
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"extras": {"surface": {"values": [[0, n, 3]]},
                                      "waytype": {"values": [[0, n, 7]]}}}}


class ViaTests(_FreshBudget):
    """Walks out to a chosen place and back a different way - founder request."""

    def test_the_corridor_leaves_both_ends_open(self):
        from core.walking.generate import CORRIDOR_OPEN_M, corridor
        poly = corridor(LINE)
        lats = [pt[1] for p in poly["coordinates"] for pt in p[0]]
        open_deg = CORRIDOR_OPEN_M / 111320.0
        self.assertGreater(min(lats), 52.0 + open_deg * 0.8)
        self.assertLess(max(lats), 52.009 - open_deg * 0.8)

    def test_joining_reindexes_the_way_back(self):
        from core.walking.generate import join_features
        joined = join_features(line_feature(LINE), line_feature(LINE[::-1]))
        self.assertEqual(len(joined["geometry"]["coordinates"]), 21)
        self.assertEqual(joined["properties"]["extras"]["surface"]["values"][1][:2], [10, 20])

    def _run(self, back_status):
        from core.walking import generate as gen
        seen = []

        def handler(request):
            seen.append(request)
            body = request.read().decode()
            if "avoid_polygons" in body and back_status != 200:
                return httpx.Response(back_status, json={"error": "no route"})
            coords = LINE if len(seen) == 1 else LINE[::-1]
            return httpx.Response(200, json={"features": [line_feature(coords)]})

        os.environ["ORS_API_KEY"] = "test-key"
        try:
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            routes = asyncio.run(gen.via_walk((52.0, 13.0), (52.009, 13.0), "carrier",
                                              "Home", "the bridge", client=client))
        finally:
            os.environ.pop("ORS_API_KEY", None)
        return routes, seen

    def test_the_way_back_is_asked_to_avoid_the_way_out(self):
        routes, seen = self._run(200)
        self.assertIn("avoid_polygons", seen[1].read().decode())
        self.assertEqual(routes[0].via["label"], "the bridge")

    def test_with_no_other_way_back_it_says_so(self):
        routes, seen = self._run(404)
        self.assertEqual(len(routes), 1)
        self.assertTrue(any("avoids the way out" in n for n in routes[0].notes))

    def test_a_via_walk_is_never_turned_back_before_the_checkpoint(self):
        from core.walking.catalogue import assess_route
        from core.walking.profiles import CarrierSetup
        routes, _ = self._run(200)
        card = assess_route(routes[0], "carrier", CarrierSetup(), minutes=10)
        self.assertNotEqual(card["fit"]["kind"], "turned")
        self.assertIn("via", [m["kind"] for m in card["markers"]])


class WeightingFallbackTests(_FreshBudget):
    """Greener and quieter failed on production, 9 Oct, with the documented
    example's {"factor": ...} form. Each form is tried in turn, and if the
    provider takes neither, ordinary walks are made and say so."""

    def setUp(self):
        super().setUp()
        os.environ["ORS_API_KEY"] = "test-key"

    def tearDown(self):
        from core.walking import generate as gen
        gen._WEIGHT_FORM = None
        os.environ.pop("ORS_API_KEY", None)

    def _run(self, accept):
        """accept(body_text) -> bool decides whether a request succeeds."""
        from core.walking import generate as gen
        seen = []

        def handler(request):
            text = request.read().decode()
            seen.append(text)
            if not accept(text):
                return httpx.Response(400, json={"error": {
                    "code": 2003, "message": "Parameter 'weightings' value 0.8 at 52.1,13.2"}})
            return httpx.Response(200, json={"features": [feature()]})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with self.assertLogs("driftway", level="WARNING") as logs:
            routes = asyncio.run(gen.generate((52.0, 13.0), "carrier", 30, "x",
                                              client, character="green"))
            log = "\n".join(logs.output)
        return routes, seen, log

    def test_the_object_form_is_tried_when_the_integer_form_is_refused(self):
        from core.walking import generate as gen
        routes, seen, _ = self._run(lambda t: '"factor"' in t)
        self.assertEqual(len(routes), 3)
        self.assertEqual(gen._WEIGHT_FORM, "factor")
        self.assertFalse(any("wasn't accepted" in n for n in routes[0].notes))

    def test_the_integer_form_goes_first(self):
        from core.walking import generate as gen
        seen = []

        def handler(request):
            seen.append(request.read().decode())
            return httpx.Response(200, json={"features": [feature()]})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        asyncio.run(gen.generate((52.0, 13.0), "carrier", 30, "x", client, character="green"))
        self.assertEqual(len(seen), 3)                       # one call per walk
        self.assertTrue(all(json.loads(t)["options"]["profile_params"]
                            == {"weightings": {"green": 1}} for t in seen))
        self.assertEqual(gen._WEIGHT_FORM, "int")

    def test_a_walk_says_when_the_data_behind_a_weighting_is_flat(self):
        from core.walking import generate as gen
        flat = feature()
        flat["properties"]["extras"]["noise"] = {"values": [[0, 5, 7]]}
        varied = feature()
        varied["properties"]["extras"]["noise"] = {"values": [[0, 2, 7], [2, 5, 3]]}
        self.assertTrue(gen.flat_weight_data(flat, "quiet"))
        self.assertFalse(gen.flat_weight_data(varied, "quiet"))
        self.assertFalse(gen.flat_weight_data(feature(), "quiet"))   # not sent: no claim

        def handler(request):
            return httpx.Response(200, json={"features": [flat]})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        routes = asyncio.run(gen.generate((52.0, 13.0), "carrier", 30, "x", client,
                                          character="quiet"))
        self.assertTrue(any("doesn't vary along this walk" in n for n in routes[0].notes))

    def test_if_no_form_is_accepted_ordinary_walks_say_so(self):
        routes, _, _ = self._run(lambda t: "weightings" not in t)
        self.assertEqual(len(routes), 3)
        self.assertTrue(any("wasn't accepted" in n for n in routes[0].notes))

    def test_the_logged_error_has_no_numbers_in_it(self):
        _, _, log = self._run(lambda t: "weightings" not in t)
        self.assertIn("code 2003", log)
        self.assertNotIn("52.1", log)
        self.assertNotIn("0.8", log)



def offset_line(east_m):
    """A different line between the same two ends, bowed east by east_m."""
    import math
    d = east_m / (111320.0 * math.cos(math.radians(52.0)))
    pts = []
    for i in range(11):
        bow = d * math.sin(math.pi * i / 10)
        pts.append([13.0 + bow, 52.0 + i * 0.0009, 30])
    return pts


class ViaAlternativesTests(_FreshBudget):
    """More than one walk through a checkpoint - founder feedback, 9 Oct: a
    known treeline route never came up because only one walk was made."""

    def _run(self, distinct=True):
        from core.walking import generate as gen
        calls = []

        def handler(request):
            calls.append(request.read().decode())
            n = len(calls)
            # Each new request bows further east unless asked to repeat.
            bow = (n * 120) if distinct else 0
            line = offset_line(bow)
            # Ways back run north to south.
            if n % 2 == 0:
                line = line[::-1]
            return httpx.Response(200, json={"features": [line_feature(line)]})

        os.environ["ORS_API_KEY"] = "test-key"
        try:
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            return asyncio.run(gen.via_walk((52.0, 13.0), (52.009, 13.0), "carrier",
                                            "Home", "the avenue", client=client)), calls
        finally:
            os.environ.pop("ORS_API_KEY", None)

    def test_up_to_three_different_walks_are_offered(self):
        routes, calls = self._run(distinct=True)
        self.assertEqual(len(routes), 3)
        self.assertEqual([r.name for r in routes],
                         ["Via the avenue", "Via the avenue, option 2",
                          "Via the avenue, option 3"])

    def test_later_variants_avoid_the_paths_already_used(self):
        _, calls = self._run(distinct=True)
        self.assertNotIn("avoid_polygons", calls[0])          # first way out
        self.assertTrue(all("avoid_polygons" in c for c in calls[1:]))

    def test_a_repeat_of_an_earlier_walk_is_dropped(self):
        routes, _ = self._run(distinct=False)
        self.assertEqual(len(routes), 1)

    def test_calls_stop_when_the_budget_is_spent(self):
        from core.walking import generate as gen
        gen.CALL_WINDOWS_SAVED = gen.CALL_WINDOWS
        gen.CALL_WINDOWS = ((60, 2), (86400, 1800))
        try:
            routes, calls = self._run(distinct=True)
        finally:
            gen.CALL_WINDOWS = gen.CALL_WINDOWS_SAVED
        self.assertEqual(len(calls), 2)          # refused after the budget
        self.assertEqual(len(routes), 1)         # what was found is kept

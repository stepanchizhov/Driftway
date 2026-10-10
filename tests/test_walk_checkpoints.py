"""
Checkpoints placed by search or on the map - 10 Oct 2026.

A checkpoint means "visit this point". These tests hold the contract at both
boundaries: what reaches openrouteservice ([lng, lat], search radii, the
profile's own access options on both legs), and what the parent is told when
the provider moves the point, cannot reach it, or cannot fit it in the time.

No network: provider answers are built in the documented shape, including its
error bodies ({"error": {"code": 2010, "message": "Could not find point 1:
..."}}). Coordinates are synthetic, not anyone's.
"""

import asyncio
import json
import math
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import httpx  # noqa: E402

from test_identity_auth0 import ADMIN, _fresh, _token  # noqa: E402

START = (52.0, 13.0)
VIA = (52.009, 13.0)                 # 1 km north
M_PER_DEG_LNG = 111320.0 * math.cos(math.radians(52.009))


def line(end_east_m=0.0, bow_m=0.0, n=11):
    """START to a point near VIA, [lng, lat, ele], optionally bowed east."""
    pts = []
    for i in range(n):
        t = i / (n - 1)
        east = bow_m * math.sin(math.pi * t) + end_east_m * t
        pts.append([13.0 + east / M_PER_DEG_LNG, 52.0 + t * 0.009, 30])
    return pts


def fc(coords):
    n = len(coords) - 1
    return {"features": [{"type": "Feature",
                          "geometry": {"type": "LineString", "coordinates": coords},
                          "properties": {"extras": {"surface": {"values": [[0, n, 3]]},
                                                    "waytype": {"values": [[0, n, 7]]}}}}]}


def ors_error(code, point, live=True):
    """The provider's "point not found" body. `live` is the wording seen from
    the public API on 10 Oct 2026; the other is an older release's."""
    msg = (f"Could not find routable point within a radius of 150.0 meters of "
           f"specified coordinate {point}: 13.0000000 52.0090000." if live
           else f"Could not find point {point}: 13.0 52.009 within a radius of 150.0 meters.")
    return {"error": {"code": code, "message": msg}}


class _Base(unittest.TestCase):
    def setUp(self):
        from core.walking import generate as gen
        gen._CALL_BUDGET = None
        gen._WEIGHT_FORM = None
        os.environ["ORS_API_KEY"] = "test-key"

    def tearDown(self):
        os.environ.pop("ORS_API_KEY", None)

    def run_via(self, handler, profile="carrier", via=VIA, minutes=None, character="any"):
        from core.walking import generate as gen
        seen = []

        def record(request):
            seen.append(request)
            return handler(request, len(seen))

        client = httpx.AsyncClient(transport=httpx.MockTransport(record))
        routes = asyncio.run(gen.via_walk(START, via, profile, "Start", "the oak",
                                          character=character, client=client,
                                          minutes=minutes))
        return routes, seen


def out_and_back(out, back=None):
    """Way out on odd calls, way back on even ones."""
    back = back if back is not None else out[::-1]

    def handler(request, n):
        return httpx.Response(200, json=fc(out if n % 2 else back))
    return handler


class RequestContractTests(_Base):
    def test_coordinates_go_as_lng_lat_with_search_radii(self):
        _, seen = self.run_via(out_and_back(line()))
        first = json.loads(seen[0].read())
        self.assertEqual(first["coordinates"], [[13.0, 52.0], [13.0, 52.009]])
        self.assertEqual(first["radiuses"], [400, 150])
        back = json.loads(seen[1].read())
        self.assertEqual(back["coordinates"], [[13.0, 52.009], [13.0, 52.0]])
        self.assertEqual(back["radiuses"], [150, 400])

    def test_every_profile_keeps_its_access_rules_on_both_legs(self):
        expected = {"pram": "wheelchair", "carrier": "foot-walking",
                    "walker": "foot-walking"}
        for profile, ors in expected.items():
            with self.subTest(profile=profile):
                self.setUp()
                routes, seen = self.run_via(out_and_back(line(bow_m=150)), profile=profile)
                self.assertTrue(routes)
                self.assertTrue(all(f"/{ors}/" in str(r.url) for r in seen))
                bodies = [json.loads(r.read()) for r in seen]
                steps = [("steps" in b["options"].get("avoid_features", [])) for b in bodies]
                self.assertEqual(all(steps), profile == "pram")
                self.assertTrue(any(s for s in steps) == (profile == "pram"))


class SnappingTests(_Base):
    def test_a_point_on_the_path_is_visited(self):
        routes, _ = self.run_via(out_and_back(line(end_east_m=10)))
        self.assertLessEqual(routes[0].via["offset_m"], 25)
        self.assertEqual(routes[0].via["requested"], {"lat": VIA[0], "lng": VIA[1]})

    def test_a_materially_moved_point_is_reported_not_hidden(self):
        from core.walking.catalogue import assess_route
        from core.walking.profiles import CarrierSetup
        routes, _ = self.run_via(out_and_back(line(end_east_m=80)))
        self.assertTrue(70 <= routes[0].via["offset_m"] <= 90)
        # The walk goes to where the provider routed, and says so on the map.
        card = assess_route(routes[0], "carrier", CarrierSetup(), 30)
        kinds = [m["kind"] for m in card["markers"]]
        self.assertIn("via", kinds)
        self.assertIn("via_requested", kinds)
        via = next(m for m in card["markers"] if m["kind"] == "via")
        self.assertNotAlmostEqual(via["lng"], VIA[1], places=4)

    def test_a_variant_that_misses_the_checkpoint_is_dropped(self):
        far = line(end_east_m=200, bow_m=300)

        def handler(request, n):
            if n == 3:                       # second variant's way out
                return httpx.Response(200, json=fc(far))
            if n == 4:                       # ... and its way back
                return httpx.Response(200, json=fc(far[::-1]))
            out = line(bow_m=150) if n % 2 else line(bow_m=-150)[::-1]
            return httpx.Response(200, json=fc(out))

        routes, _ = self.run_via(handler)
        from core.walking.generate import closest_m
        for r in routes:
            pts = [[p[1], p[0]] for s in r.sections for p in s.geometry]
            self.assertLessEqual(closest_m(pts, (r.via["lat"], r.via["lng"])), 25)


class FailureTests(_Base):
    def test_no_usable_way_near_the_checkpoint_asks_to_move_it(self):
        from core.walking.generate import CheckpointProblem
        with self.assertRaises(CheckpointProblem) as e:
            self.run_via(lambda r, n: httpx.Response(404, json=ors_error(2010, 1)),
                         profile="pram")
        self.assertEqual(e.exception.code, "unreachable")
        self.assertIn("a pram", str(e.exception))
        self.assertIn("150 m", str(e.exception))

    def test_the_older_wording_is_read_too(self):
        from core.walking.generate import CheckpointProblem
        with self.assertRaises(CheckpointProblem) as e:
            self.run_via(lambda r, n: httpx.Response(404, json=ors_error(2010, 1, live=False)))
        self.assertEqual(e.exception.code, "unreachable")

    def test_no_route_to_the_checkpoint_is_said_plainly(self):
        from core.walking.generate import CheckpointProblem
        with self.assertRaises(CheckpointProblem) as e:
            self.run_via(lambda r, n: httpx.Response(404, json={
                "error": {"code": 2009, "message": "Route could not be found"}}))
        self.assertEqual(e.exception.code, "no_route")

    def test_an_unfindable_start_is_not_blamed_on_the_checkpoint(self):
        from core.walking.generate import CheckpointProblem, GenerationUnavailable
        with self.assertRaises(GenerationUnavailable) as e:
            self.run_via(lambda r, n: httpx.Response(404, json=ors_error(2010, 0)))
        self.assertNotIsInstance(e.exception, CheckpointProblem)
        self.assertIn("start", str(e.exception))

    def test_a_checkpoint_too_far_for_the_time_is_refused_before_any_call(self):
        from core.walking.generate import CheckpointProblem
        calls = []
        with self.assertRaises(CheckpointProblem) as e:
            self.run_via(lambda r, n: calls.append(n), minutes=10)
        self.assertEqual(calls, [])
        self.assertEqual(e.exception.code, "too_far")
        self.assertEqual(e.exception.minimum_minutes, 31)   # 2.0016 km at 4 km/h

    def test_a_checkpoint_at_the_start_is_refused(self):
        from core.walking.generate import CheckpointProblem
        with self.assertRaises(CheckpointProblem) as e:
            self.run_via(out_and_back(line()), via=(52.0002, 13.0))
        self.assertEqual(e.exception.code, "too_close")


class RetracingTests(_Base):
    def test_a_necessary_shared_passage_still_gives_a_walk_and_says_so(self):
        from core.walking.catalogue import assess_route
        from core.walking.profiles import CarrierSetup

        def handler(request, n):
            body = request.read().decode()
            if "avoid_polygons" in body:     # no way back avoiding the way out
                return httpx.Response(404, json={"error": {"code": 2009,
                                                           "message": "none"}})
            return httpx.Response(200, json=fc(line() if n == 1 else line()[::-1]))

        routes, _ = self.run_via(handler)
        self.assertEqual(len(routes), 1)
        self.assertTrue(any("same ground twice" in n for n in routes[0].notes))
        card = assess_route(routes[0], "carrier", CarrierSetup(), 30)
        self.assertGreaterEqual(card["retrace_share"], 0.35)   # shown, measured


class EndpointTests(unittest.TestCase):
    def setUp(self):
        os.environ["WALKING_ENABLED"] = "true"
        os.environ["ORS_API_KEY"] = "test-key"
        from core.walking import generate as gen
        gen._CALL_BUDGET = None
        gen._WEIGHT_FORM = None
        self.client, _ = _fresh()
        minted = self.client.post("/api/admin/beta-invites",
                                  headers={"X-Admin-Token": ADMIN}).json()
        token = _token(sub="auth0|checkpoint")
        self.client.post("/api/auth/accept-beta-invite",
                         json={"invite_token": minted["invite_token"]},
                         headers={"Authorization": f"Bearer {token}"})
        self.auth = {"Authorization": f"Bearer {token}"}
        import routes.walks as walks
        walks._generate_caller = walks.SlidingWindowLimiter()
        walks._generate_global = walks.SlidingWindowLimiter()

    def tearDown(self):
        self.client.close()
        for k in ("WALKING_ENABLED", "ORS_API_KEY"):
            os.environ.pop(k, None)

    def post(self, body, handler=None):
        real = httpx.AsyncClient
        handler = handler or (lambda r: httpx.Response(200, json=fc(line(bow_m=150))))
        with mock.patch("core.walking.generate.httpx.AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler))):
            return self.client.post("/api/walks/generate", json=body, headers=self.auth)

    def body(self, **kw):
        b = {"profile": "walker", "minutes": 30,
             "start": {"lat": START[0], "lng": START[1]},
             "via": {"lat": VIA[0], "lng": VIA[1]}, "via_label": "the oak"}
        b.update(kw)
        return b

    def test_out_of_range_or_non_finite_coordinates_are_refused(self):
        for via in ({"lat": 91, "lng": 0}, {"lat": 0, "lng": 181}):
            self.assertEqual(self.post(self.body(via=via)).status_code, 422)
        raw = json.dumps(self.body(via={"lat": float("nan"), "lng": 0.0}))
        r = self.client.post("/api/walks/generate", content=raw, headers={
            **self.auth, "Content-Type": "application/json"})
        self.assertEqual(r.status_code, 422)
        raw = json.dumps(self.body(via={"lat": float("inf"), "lng": 0.0}))
        r = self.client.post("/api/walks/generate", content=raw, headers={
            **self.auth, "Content-Type": "application/json"})
        self.assertEqual(r.status_code, 422)

    def test_the_outcome_names_requested_and_routed_points(self):
        r = self.post(self.body())
        self.assertEqual(r.status_code, 200, r.text)
        cp = r.json()["checkpoint"]
        self.assertEqual(cp["requested"], {"lat": VIA[0], "lng": VIA[1]})
        self.assertFalse(cp["needs_confirmation"])

    def test_a_moved_point_needs_the_parents_confirmation(self):
        moved = line(end_east_m=80, bow_m=150)
        r = self.post(self.body(), lambda req: httpx.Response(200, json=fc(moved)))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["checkpoint"]["needs_confirmation"])

    def test_a_checkpoint_problem_is_a_422_the_screen_can_act_on(self):
        r = self.post(self.body(minutes=10))
        self.assertEqual(r.status_code, 422)
        detail = r.json()["detail"]
        self.assertEqual(detail["code"], "too_far")
        self.assertEqual(detail["minimum_minutes"], 31)

    def test_walks_longer_than_asked_are_flagged_not_trimmed(self):
        # 1 km away as the crow flies (fits 30 min), but the only paths bow
        # far out, so every walk through it is longer than asked.
        long_way = line(bow_m=900)
        r = self.post(self.body(), lambda req: httpx.Response(200, json=fc(long_way)))
        self.assertEqual(r.status_code, 200, r.text)
        cp = r.json()["checkpoint"]
        self.assertTrue(cp["over_time"])
        self.assertGreater(cp["shortest_minutes"], 35)
        for w in r.json()["walks"]:
            self.assertEqual(w["fit"]["kind"], "longer")      # never "turned"


if __name__ == "__main__":
    unittest.main()

"""
When a provider is lost - 10 Oct 2026.

openrouteservice moved its API without Driftway noticing, and walk
generation failed for a day. TomTom carries every drive, every Meet Halfway
and every place search, so losing it would stop the app. With an
openrouteservice key set, TomTom's failures now hand over to it:

  * a refusal (key, quota), throttling, a server error or no network stands
    TomTom down for a cooldown, and its calls go to openrouteservice;
  * "no route between these points" is TomTom's answer, not a failure;
  * routes from the stand-in say their time has no live traffic.

No network: provider answers are built in their documented shapes, checked
live the same day.
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

from core import ors, router as R, search as S  # noqa: E402
from core.models import Coord  # noqa: E402

HOME = Coord(lat=51.4816, lng=-0.6105)
A1 = Coord(lat=51.50, lng=-0.64)


def ors_route(duration_s=1800.0, distance_m=19000.0, step_types=(11, 0, 6, 10)):
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "geometry": {"type": "LineString",
                     "coordinates": [[-0.6105, 51.4816], [-0.64, 51.50], [-0.6105, 51.4816]]},
        "properties": {"summary": {"duration": duration_s, "distance": distance_m},
                       "segments": [{"steps": [{"type": t} for t in step_types]}]}}]}


class _Base(unittest.TestCase):
    def setUp(self):
        R._tomtom_down_until = 0.0
        ors.reset_budgets()
        self.env = mock.patch.dict(os.environ, {"ORS_API_KEY": "ors-test"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        R._tomtom_down_until = 0.0

    @staticmethod
    def client(handler, seen=None):
        def h(request):
            if seen is not None:
                seen.append(request)
            return handler(request)
        return httpx.AsyncClient(transport=httpx.MockTransport(h))


class OrsRouterTests(_Base):
    def test_a_route_is_read_and_says_it_has_no_live_traffic(self):
        seen = []
        r = R.ORSRouter(self.client(lambda q: httpx.Response(200, json=ors_route()), seen))
        ev = asyncio.run(r.evaluate(HOME, HOME, [A1], "quiet"))
        self.assertEqual(ev.minutes, 30.0)
        self.assertEqual(ev.distance_km, 19.0)
        self.assertFalse(ev.live_traffic)
        self.assertFalse(ev.has_uturn)
        body = json.loads(seen[0].read())
        self.assertEqual(body["coordinates"][1], [-0.64, 51.50])        # [lng, lat]
        self.assertEqual(body["options"]["avoid_features"], ["highways"])
        self.assertIn("/openrouteservice/v2/directions/driving-car/geojson", str(seen[0].url))

    def test_a_u_turn_instruction_counts_as_turning_round(self):
        r = R.ORSRouter(self.client(lambda q: httpx.Response(
            200, json=ors_route(step_types=(11, 9, 10)))))
        self.assertTrue(asyncio.run(r.evaluate(HOME, HOME, [A1], "mixed")).has_uturn)

    def test_the_matrix_is_minutes_by_origin_and_destination(self):
        r = R.ORSRouter(self.client(lambda q: httpx.Response(
            200, json={"durations": [[385.62, None]]})))
        grid = asyncio.run(r.travel_matrix([HOME], [A1, HOME], "mixed"))
        self.assertEqual(grid, [[6.4, None]])


class FailoverRouterTests(_Base):
    def _pair(self, tomtom_status, tomtom_seen, ors_seen):
        tomtom = R.TomTomRouter("tt-test", client=self.client(
            lambda q: httpx.Response(tomtom_status, json={"error": "x"}), tomtom_seen))
        backup = R.ORSRouter(self.client(lambda q: httpx.Response(200, json=ors_route()),
                                         ors_seen))
        return R.FailoverRouter(tomtom, backup)

    def test_a_refusing_tomtom_hands_over_and_stays_stood_down(self):
        tt, o = [], []
        f = self._pair(403, tt, o)
        first = asyncio.run(f.evaluate(HOME, HOME, [A1], "mixed"))
        self.assertIsNotNone(first)
        self.assertFalse(first.live_traffic)
        self.assertEqual(f.name, "openrouteservice")
        asyncio.run(f.evaluate(HOME, HOME, [A1], "mixed"))
        self.assertEqual(len(tt), 1)          # not asked again during the cooldown
        self.assertEqual(len(o), 2)

    def test_no_route_is_an_answer_not_a_failure(self):
        tt, o = [], []
        f = self._pair(400, tt, o)
        self.assertIsNone(asyncio.run(f.evaluate(HOME, HOME, [A1], "mixed")))
        self.assertEqual(o, [])
        self.assertTrue(R.tomtom_available())

    def test_a_tomtom_server_error_hands_over(self):
        tt, o = [], []
        f = self._pair(503, tt, o)
        self.assertIsNotNone(asyncio.run(f.evaluate(HOME, HOME, [A1], "mixed")))
        self.assertFalse(R.tomtom_available())

    def test_tomtom_is_tried_again_after_the_cooldown(self):
        R._tomtom_down_until = 0.0
        R._tomtom_failed("test")
        self.assertFalse(R.tomtom_available())
        with mock.patch("time.monotonic", return_value=R._tomtom_down_until + 1):
            self.assertTrue(R.tomtom_available())

    def test_the_matrix_hands_over_too(self):
        tomtom = R.TomTomRouter("tt-test", client=self.client(
            lambda q: httpx.Response(429, json={})))
        backup = R.ORSRouter(self.client(lambda q: httpx.Response(
            200, json={"durations": [[600.0]]})))
        grid = asyncio.run(R.FailoverRouter(tomtom, backup).travel_matrix([HOME], [A1], "mixed"))
        self.assertEqual(grid, [[10.0]])


class FactoryTests(_Base):
    def test_tomtom_with_a_stand_in_when_both_keys_are_set(self):
        with mock.patch.dict(os.environ, {"ROUTING_PROVIDER": "tomtom", "TOMTOM_API_KEY": "t"}):
            self.assertIsInstance(R.get_router(), R.FailoverRouter)
            self.assertIsInstance(S.get_search(), S.FailoverSearch)

    def test_tomtom_alone_without_an_openrouteservice_key(self):
        with mock.patch.dict(os.environ, {"ROUTING_PROVIDER": "tomtom", "TOMTOM_API_KEY": "t",
                                          "ORS_API_KEY": ""}):
            self.assertIsInstance(R.get_router(), R.TomTomRouter)
            self.assertIsInstance(S.get_search(), S.TomTomSearch)

    def test_openrouteservice_when_the_tomtom_key_is_missing(self):
        with mock.patch.dict(os.environ, {"ROUTING_PROVIDER": "tomtom", "TOMTOM_API_KEY": ""}):
            self.assertIsInstance(R.get_router(), R.ORSRouter)
            self.assertIsInstance(S.get_search(), S.PeliasSearch)


class TrafficNoteTests(unittest.TestCase):
    def test_a_route_without_live_traffic_says_so(self):
        from core.generator import NO_TRAFFIC_NOTE, _with_traffic_note
        ev = R.EvaluatedRoute(anchors=[], minutes=30, distance_km=19,
                              road_mix=R._infer_mix("mixed"), live_traffic=False)
        self.assertEqual(_with_traffic_note(ev, None), NO_TRAFFIC_NOTE)
        self.assertEqual(_with_traffic_note(ev, "doubles back once"),
                         f"doubles back once; {NO_TRAFFIC_NOTE}")
        ev.live_traffic = True
        self.assertIsNone(_with_traffic_note(ev, None))


class FailoverSearchTests(_Base):
    PELIAS = {"features": [
        {"geometry": {"coordinates": [-0.606415, 51.483876]},
         "properties": {"layer": "postalcode", "name": "SL4 1NJ", "gid": "pc1",
                        "label": "SL4 1NJ, Windsor, England, United Kingdom"}},
        {"geometry": {"coordinates": [-0.621413, 51.48596]},
         "properties": {"layer": "venue", "name": "Windsor Leisure Centre", "gid": "v1",
                        "label": "Windsor Leisure Centre, Windsor, England, United Kingdom"}},
    ]}

    def _search(self, tomtom_status, tomtom_body=None):
        tomtom = S.TomTomSearch("tt-test", client=self.client(
            lambda q: httpx.Response(tomtom_status, json=tomtom_body or {})))
        seen = []
        backup = S.PeliasSearch(self.client(lambda q: httpx.Response(200, json=self.PELIAS), seen))
        return S.FailoverSearch(tomtom, backup), seen

    def test_an_unavailable_tomtom_hands_over_to_place_search(self):
        f, seen = self._search(403)
        places = asyncio.run(f.search("sl4 1nj", HOME, 5))
        self.assertEqual([p.kind for p in places], ["postcode", "poi"])
        self.assertEqual(places[0].detail, "Windsor, England")
        self.assertFalse(places[0].approximate)
        self.assertIn("/pelias/v1/autocomplete", str(seen[0].url))
        self.assertEqual(seen[0].headers["Authorization"], "ors-test")

    def test_no_matches_is_an_answer_not_a_failure(self):
        f, seen = self._search(200, {"results": []})
        self.assertEqual(asyncio.run(f.search("zzzz", HOME, 5)), [])
        self.assertEqual(seen, [])


class SecondAddressTests(_Base):
    def test_a_refused_request_goes_to_the_second_address_with_its_key(self):
        seen = []

        def handler(request):
            if "primary.test" in str(request.url):
                return httpx.Response(403, json={"error": "Quota exceeded"})
            return httpx.Response(200, json=ors_route())

        with mock.patch.dict(os.environ, {"ORS_BASE_URL": "https://primary.test/ors",
                                          "ORS_FALLBACK_BASE_URL": "http://selfhosted.test/ors",
                                          "ORS_FALLBACK_API_KEY": "own"}):
            ev = asyncio.run(R.ORSRouter(self.client(handler, seen)).evaluate(
                HOME, HOME, [A1], "mixed"))
        self.assertIsNotNone(ev)
        self.assertEqual(len(seen), 2)
        self.assertTrue(str(seen[1].url).startswith("http://selfhosted.test/ors/v2/"))
        self.assertEqual(seen[1].headers["Authorization"], "own")

    def test_an_answer_about_the_request_is_not_retried_elsewhere(self):
        seen = []
        with mock.patch.dict(os.environ, {"ORS_FALLBACK_BASE_URL": "http://selfhosted.test/ors"}):
            asyncio.run(R.ORSRouter(self.client(
                lambda q: httpx.Response(404, json={"error": {"code": 2009}}), seen)).evaluate(
                HOME, HOME, [A1], "mixed"))
        self.assertEqual(len(seen), 1)


if __name__ == "__main__":
    unittest.main()


class ProviderCheckTests(_Base):
    """The daily check that would have caught the moved API the morning it
    started."""

    def _client(self, ors_status=200, extra_headers=None):
        def handler(request):
            url = str(request.url)
            h = dict(extra_headers or {})
            if "tomtom.com/routing" in url:
                return httpx.Response(200, json={"routes": [{}]})
            if "tomtom.com/search" in url:
                return httpx.Response(200, json={"results": [{}]})
            if "/pelias/" in url:
                return httpx.Response(200, json={"features": [{}]})
            if "/openrouteservice/" in url:
                return httpx.Response(ors_status, json={"error": "Quota exceeded"}
                                      if ors_status != 200 else {"durations": [[1]]},
                                      headers={"x-ratelimit-remaining": "1999", **h})
            if "tile.openstreetmap.org" in url:
                return httpx.Response(200, content=b"png")
            if "openid-configuration" in url:
                return httpx.Response(200, json={})
            return httpx.Response(404)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    def _run(self, **kw):
        from core import provider_check
        with mock.patch.dict(os.environ, {"TOMTOM_API_KEY": "t", "AUTH0_DOMAIN": "x.auth0.test"}):
            return asyncio.run(provider_check.run_checks(self._client(**kw)))

    def test_every_provider_is_checked_and_reported(self):
        r = self._run()
        self.assertTrue(r["ok"])
        self.assertEqual(set(r["providers"]), {"tomtom_routing", "tomtom_search",
                                               "ors_directions", "ors_geocode", "ors_matrix",
                                               "auth0", "osm_tiles"})
        self.assertEqual(r["providers"]["ors_directions"]["detail"], "1999 left today")

    def test_a_refusing_provider_fails_the_check(self):
        r = self._run(ors_status=403)
        self.assertFalse(r["ok"])
        self.assertFalse(r["providers"]["ors_directions"]["ok"])
        self.assertEqual(r["providers"]["ors_directions"]["status"], 403)
        self.assertTrue(r["providers"]["tomtom_search"]["ok"])

    def test_an_announced_retirement_is_reported(self):
        r = self._run(extra_headers={"Sunset": "Mon, 28 Sep 2026 00:00:00 GMT"})
        self.assertIn("Sunset", r["providers"]["ors_directions"]["warning"])

    def test_results_are_cached_so_the_endpoint_cannot_spend_quota(self):
        from core import provider_check
        provider_check._cache.update(at=0.0, result=None)
        calls = []

        async def fake():
            calls.append(1)
            return {"ok": True, "providers": {}}

        with mock.patch.object(provider_check, "run_checks", fake):
            asyncio.run(provider_check.cached_checks())
            asyncio.run(provider_check.cached_checks())
        self.assertEqual(len(calls), 1)
        provider_check._cache.update(at=0.0, result=None)

    def test_health_names_the_stand_in(self):
        from test_identity_auth0 import _fresh
        client, _ = _fresh()
        try:
            fb = client.get("/api/health").json()["fallbacks"]
        finally:
            client.close()
        self.assertEqual(fb["driving_and_search"], "openrouteservice")
        self.assertFalse(fb["tomtom_stood_down"])

"""
Roadworks from TomTom's traffic incidents where Street Manager doesn't reach
(core/incidents.py; founder, 13 Oct 2026: "What about Wales, Scotland and
NI?"). Synthetic incidents in TomTom's documented shape; no network.

A straight synthetic road north along 13.0 E from 52.000 to 52.010, nobody's
address.
"""

import asyncio
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import httpx  # noqa: E402

from core import incidents, roadworks  # noqa: E402
from core.models import Coord  # noqa: E402

DRIVE = [(52.0 + i * 0.0005, 13.0) for i in range(21)]         # northwards
REAL_CLIENT = httpx.AsyncClient


def incident(coords, cat=9, desc="Roadworks", road="B39", iid="1"):
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[b, a] for a, b in coords]},
            "properties": {"id": iid, "iconCategory": cat, "events": [{"description": desc, "code": 701}],
                           "roadNumbers": [road] if road else [], "from": "Somewhere"}}


def found(incs, sm_works=None):
    """works_for over DRIVE with these incidents (and Street Manager rows)."""
    with roadworks.lookup_for_request(None):
        lk = roadworks._lookup.get()
        lk.incidents = incidents.parse({"incidents": incs})
        if sm_works is not None:
            with mock.patch.object(roadworks, "works_along", lambda s, g: list(sm_works)):
                lk.session = object()
                return roadworks.works_for(DRIVE)
        return roadworks.works_for(DRIVE)


class ClassifyTests(unittest.TestCase):
    def test_alternating_traffic_stops_cars_and_plain_roadworks_dont_say(self):
        self.assertEqual(incidents.classify({"iconCategory": 7, "events": [{"description": "Single alternate line traffic"}]}),
                         "alternating_traffic")
        self.assertIn("alternating_traffic", roadworks.STOPPING)
        self.assertEqual(incidents.classify({"iconCategory": 9, "events": [{"description": "Roadworks"}]}), "roadworks")
        self.assertEqual(incidents.classify({"iconCategory": 8, "events": [{"description": "Closed"}]}), "road_closure")
        # A lane closed with traffic still flowing is not kept.
        self.assertIsNone(incidents.classify({"iconCategory": 7, "events": [{"description": "Lane closed"}]}))


class OnTheDriveTests(unittest.TestCase):
    def test_works_along_the_drive_are_on_it(self):
        got = found([incident([(52.004, 13.0), (52.006, 13.0)])])
        self.assertEqual([w.street for w in got], ["B39"])
        self.assertEqual(roadworks.describe(got), ["B39: roadworks, traffic control not known"])
        self.assertEqual(roadworks.sources(got), ["tomtom"])

    def test_a_street_the_drive_only_crosses_is_not_on_it(self):
        crossing = incident([(52.005, 12.998), (52.005, 13.002)], cat=8, desc="Closed", road="Side St")
        self.assertEqual(found([crossing]), [])

    def test_a_closure_only_counts_the_way_the_drive_goes(self):
        north = incident([(52.004, 13.0), (52.006, 13.0)], cat=8, desc="Closed", iid="n")
        south = incident([(52.006, 13.0), (52.004, 13.0)], cat=8, desc="Closed", iid="s")
        self.assertEqual(len(found([north])), 1)
        self.assertEqual(found([south]), [])

    def test_both_directions_of_the_same_works_count_once(self):
        a = incident([(52.004, 13.0), (52.006, 13.0)], iid="a")
        b = incident([(52.0061, 13.00005), (52.0041, 13.00005)], iid="b")
        self.assertEqual(len(found([a, b])), 1)

    def test_street_managers_record_wins_in_england(self):
        sm = roadworks.Roadwork(work_ref="SM1", street="B39", control="two_way_signals",
                                points_json=json.dumps([[52.005, 13.0]]), status="in_progress")
        got = found([incident([(52.004, 13.0), (52.006, 13.0)])], sm_works=[sm])
        self.assertEqual([w.work_ref for w in got], ["SM1"])


class FetchTests(unittest.TestCase):
    def setUp(self):
        incidents.reset_cache()

    def test_one_call_per_area_then_the_cached_answer(self):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"incidents": [incident([(52.004, 13.0), (52.006, 13.0)])]})

        with mock.patch.dict(os.environ, {"TOMTOM_API_KEY": "tt-test"}):
            for _ in range(2):
                got = asyncio.run(incidents.fetch(51.9, 12.9, 52.1, 13.1,
                                                  REAL_CLIENT(transport=httpx.MockTransport(handler))))
        self.assertEqual(len(got), 1)
        self.assertEqual(len(seen), 1)
        self.assertIn("categoryFilter=7%2C8%2C9", str(seen[0].url))

    def test_too_large_an_area_or_a_failure_gives_nothing(self):
        self.assertEqual(asyncio.run(incidents.fetch(50.0, 10.0, 53.0, 15.0)), [])
        client = REAL_CLIENT(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
        self.assertEqual(asyncio.run(incidents.fetch(51.9, 12.9, 52.1, 13.1, client)), [])

    def test_never_asked_without_live_routing(self):
        with mock.patch.dict(os.environ, {"ROUTING_PROVIDER": "mock", "TOMTOM_API_KEY": "tt"}):
            self.assertFalse(incidents.configured())
            with roadworks.lookup_for_request(None):
                with mock.patch.object(incidents, "fetch", side_effect=AssertionError("called")):
                    asyncio.run(roadworks.prefetch(Coord(lat=52.0, lng=13.0), Coord(lat=52.0, lng=13.0), 30))


class ScoringTests(unittest.TestCase):
    def test_unknown_control_counts_less_than_works_that_stop_traffic(self):
        from core import scorer
        from core.models import RoadMix
        from core.router import EvaluatedRoute
        geom = [Coord(lat=a, lng=b) for a, b in DRIVE]

        def route(control):
            r = EvaluatedRoute(anchors=[], minutes=30, distance_km=1.1, road_mix=RoadMix(), geometry=geom)
            r.bumps_checked = r.lights_checked = True
            r.works = [incidents.Incident("t", "B39", control, "[[52.005, 13.0]]")]
            return r

        unknown, stopping = route("roadworks"), route("alternating_traffic")
        self.assertLess(scorer.stop_weight(unknown), scorer.stop_weight(stopping))
        self.assertGreater(scorer.score_route(unknown, 30, "mixed"), scorer.score_route(stopping, 30, "mixed"))


if __name__ == "__main__":
    unittest.main()

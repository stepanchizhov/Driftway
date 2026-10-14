"""
What wakes your little one (founder, 13 Oct 2026: let parents "choose what
types of obstacles are better and worse for their kids. It easily can be
different for each child"). The parent's answers scale each kind of stop's
weight for one drive request (scorer.stop_preferences).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from core import calming, scorer  # noqa: E402
from core.models import Coord, GenerateRequest, RoadMix, StopPrefs  # noqa: E402
from core.router import EvaluatedRoute  # noqa: E402


def route(bumps=0, junctions=0, turns=0, minutes=30):
    r = EvaluatedRoute(anchors=[], minutes=minutes, distance_km=20, road_mix=RoadMix(),
                       geometry=[Coord(lat=52.0, lng=13.0), Coord(lat=52.1, lng=13.0)], works=[])
    r.bumps = calming.BumpCount(count=bumps, covered_km=20, covered_share=1.0)
    r.lights = calming.LightCount(junctions=junctions, pedestrian=0, covered_km=20)
    r.bumps_checked = r.lights_checked = True
    r.__dict__["_turns"] = turns
    return r


class WeightTests(unittest.TestCase):
    def setUp(self):
        self.real = scorer.turnaround_count
        scorer.turnaround_count = lambda r: r.__dict__.get("_turns", 0)

    def tearDown(self):
        scorer.turnaround_count = self.real

    def test_without_answers_the_usual_weights(self):
        r = route(bumps=4, junctions=5, turns=1)
        usual = scorer.stops_met(r)
        with scorer.stop_preferences(None):
            self.assertEqual(scorer.stops_met(r), usual)
        with scorer.stop_preferences(StopPrefs()):
            self.assertEqual(scorer.stops_met(r), usual)

    def test_what_wakes_them_counts_more_and_what_doesnt_counts_little(self):
        r = route(bumps=4)
        usual = scorer.stops_met(r)
        with scorer.stop_preferences(StopPrefs(bumps="wakes")):
            self.assertGreater(scorer.stops_met(r), usual)
        with scorer.stop_preferences(StopPrefs(bumps="fine")):
            self.assertLess(scorer.stops_met(r), usual)

    def test_the_answers_change_which_drive_goes_first(self):
        bumpy = route(bumps=6, junctions=0)
        lights = route(bumps=0, junctions=6)
        with scorer.stop_preferences(StopPrefs(bumps="wakes", lights="fine")):
            self.assertIs(scorer.calmer_lead([bumpy, lights], 30, "mixed")[0], lights)
        with scorer.stop_preferences(StopPrefs(bumps="fine", lights="wakes")):
            self.assertIs(scorer.calmer_lead([lights, bumpy], 30, "mixed")[0], bumpy)

    def test_turn_arounds_that_wake_them_weigh_on_smoothness_too(self):
        r = route(turns=1)
        usual = scorer._smoothness(r)
        with scorer.stop_preferences(StopPrefs(turns="wakes")):
            self.assertLess(scorer._smoothness(r), usual)

    def test_the_answers_last_only_for_their_request(self):
        r = route(bumps=4)
        usual = scorer.stops_met(r)
        with scorer.stop_preferences(StopPrefs(bumps="wakes")):
            pass
        self.assertEqual(scorer.stops_met(r), usual)


class RequestTests(unittest.TestCase):
    def test_a_request_carries_the_answers_or_none(self):
        req = GenerateRequest(start=Coord(lat=52.0, lng=13.0), target_minutes=30,
                              stops={"bumps": "wakes", "turns": "fine"})
        self.assertEqual(req.stops.bumps.value, "wakes")
        self.assertEqual(req.stops.lights.value, "sometimes")
        self.assertIsNone(GenerateRequest(start=Coord(lat=52.0, lng=13.0), target_minutes=30).stops)

    def test_an_unknown_answer_is_refused(self):
        with self.assertRaises(Exception):
            GenerateRequest(start=Coord(lat=52.0, lng=13.0), target_minutes=30, stops={"bumps": "always"})

    def test_the_drive_endpoint_accepts_them(self):
        from test_identity_auth0 import _fresh
        client, _ = _fresh(configured=False)
        try:
            r = client.post("/api/generate", json={
                "start": {"lat": 51.4857, "lng": -0.6214}, "target_minutes": 30,
                "stops": {"bumps": "wakes", "lights": "fine", "turns": "sometimes", "works": "wakes"}})
            self.assertEqual(r.status_code, 200, r.text)
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()

"""
Easy places to turn round (founder, 13 Oct 2026): a drive whose spike ended
at a loop round a small island needed no three-point turn. Roundabouts,
mini-roundabouts, turning circles and such loops come from OpenStreetMap
(tools/build_calming.py); a turn-around at one counts less, the card says
where, and a turn-back waypoint is moved onto one.

A synthetic world near 52.0 N 13.0 E, nobody's address.
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from core import calming, scorer, steering  # noqa: E402
from core import router as R  # noqa: E402
from core.models import Coord, RoadMix  # noqa: E402
from core.router import EvaluatedRoute  # noqa: E402
from tools import build_calming as B  # noqa: E402

BBOX = [51.99, 12.97, 52.06, 13.04]
# A spur north from the start to 52.03 and straight back: one hard turn-around.
SPUR_END = Coord(lat=52.03, lng=13.0)
# An easy place to turn 300 m beyond the spur's end, on the same road.
LOOP = [52.0327, 13.0, "loop", 16, 1]          # on a road open to cars


def spur(to_lat):
    up = [Coord(lat=52.0 + i * (to_lat - 52.0) / 40, lng=13.0) for i in range(41)]
    return up + up[-2::-1]


def region(turns):
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "test.json"), "w", encoding="utf-8") as f:
        json.dump({"region": "test", "bbox": BBOX, "as_of": "2026-10-13", "points": [],
                   "signals": [], "turns": turns}, f)
    return calming.load(d)


def route(geometry, anchors, minutes=30.0, uturn_points=()):
    return EvaluatedRoute(anchors=list(anchors), minutes=minutes, distance_km=6.6, road_mix=RoadMix(),
                          geometry=geometry, works=[], uturn_points=list(uturn_points))


class _Base(unittest.TestCase):
    turns = [LOOP]

    def setUp(self):
        # Every loaded copy of core.calming: other tests reload core, and the
        # generator imported later may hold a newer one.
        import importlib
        gen = importlib.import_module("core.generator")
        idx = region(self.turns)
        copies = {id(m): m for m in (calming, sys.modules.get("core.calming"),
                                      sys.modules[gen.easy_turns.__module__].calming) if m is not None}
        self.patches = [mock.patch.object(m, "_index", idx) for m in copies.values()]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()


class DataTests(unittest.TestCase):
    def test_a_road_that_rejoins_itself_is_a_loop_and_a_long_one_is_not(self):
        def way(i, pts):
            nodes = list(range(len(pts)))
            nodes[-1] = 1                       # back to the second point: a lollipop
            return {"type": "way", "id": i, "nodes": nodes, "tags": {"highway": "residential"},
                    "geometry": [{"lat": a, "lon": b} for a, b in pts]}
        small = [(52.0, 13.0), (52.001, 13.0), (52.0012, 13.0004), (52.0008, 13.0006), (52.001, 13.0)]
        block = [(52.0, 13.0), (52.001, 13.0), (52.004, 13.0), (52.004, 13.004), (52.001, 13.004), (52.001, 13.0)]
        turns = B.extract_turns({"elements": []}, {"elements": [way(1, small), way(2, block)]})
        self.assertEqual([t[2] for t in turns], ["loop"])
        self.assertEqual(turns[0][4], 1)

    def test_a_place_on_a_private_road_is_kept_but_not_counted_as_open(self):
        self.assertTrue(B.public_for_cars({"highway": "residential"}))
        self.assertFalse(B.public_for_cars({"highway": "residential", "access": "private"}))
        self.assertFalse(B.public_for_cars({"highway": "residential", "motor_vehicle": "destination"}))
        self.assertTrue(B.public_for_cars({"highway": "residential", "access": "no", "motorcar": "yes"}))
        self.assertFalse(B.public_for_cars({"highway": "service"}))
        tagged = {"elements": [
            {"type": "node", "id": 7, "lat": 52.01, "lon": 13.0, "tags": {"highway": "turning_circle"}},
            {"type": "node", "id": 8, "lat": 52.02, "lon": 13.0, "tags": {"highway": "turning_circle"}},
            {"type": "way", "nodes": [1, 7], "tags": {"highway": "residential"}},
            {"type": "way", "nodes": [2, 8], "tags": {"highway": "residential", "access": "private"}},
        ]}
        public = {t[0]: t[4] for t in B.extract_turns(tagged, {"elements": []})}
        self.assertEqual(public, {52.01: 1, 52.02: 0})

    def test_tagged_places_and_a_roundabout_in_pieces(self):
        tagged = {"elements": [
            {"type": "node", "lat": 52.01, "lon": 13.0, "tags": {"highway": "turning_circle"}},
            {"type": "node", "lat": 52.02, "lon": 13.0, "tags": {"highway": "mini_roundabout"}},
            {"type": "way", "tags": {"junction": "roundabout", "highway": "primary"},
             "geometry": [{"lat": 52.0300, "lon": 13.0000}, {"lat": 52.0302, "lon": 13.0003}]},
            {"type": "way", "tags": {"junction": "roundabout", "highway": "primary"},
             "geometry": [{"lat": 52.0302, "lon": 13.0003}, {"lat": 52.0300, "lon": 13.0006}]},
        ]}
        kinds = sorted(t[2] for t in B.extract_turns(tagged, {"elements": []}))
        self.assertEqual(kinds, ["mini_roundabout", "roundabout", "turning_circle"])


class FindingTests(_Base):
    def test_an_easy_place_is_found_nearby_and_not_far_away(self):
        self.assertEqual(calming.easy_turn_at(52.0327, 13.0003), "loop")
        self.assertIsNone(calming.easy_turn_at(SPUR_END.lat, SPUR_END.lng))
        near = calming.easy_places_near(SPUR_END.lat, SPUR_END.lng, 700)
        self.assertEqual([n[3] for n in near], ["loop"])
        self.assertEqual(calming.easy_places_near(52.05, 13.03, 300), [])


class ScoringTests(_Base):
    def test_a_turn_around_at_an_easy_place_counts_less_and_the_card_says_where(self):
        import importlib
        gen = importlib.import_module("core.generator")      # the copy setUp patched
        hard = route(spur(SPUR_END.lat), [SPUR_END])
        easy = route(spur(LOOP[0]), [Coord(lat=LOOP[0], lng=LOOP[1])])
        self.assertEqual(scorer.turnaround_count(hard), 1)
        self.assertEqual(scorer.turnaround_count(easy), 1)
        self.assertEqual(scorer.turn_load(hard), 1.0)
        self.assertAlmostEqual(scorer.turn_load(easy), scorer.EASY_TURN_WEIGHT)
        self.assertLess(scorer.stops_met(easy), scorer.stops_met(hard))
        req = gen.GenerateRequest(start=gen.Coord(lat=52.0, lng=13.0), target_minutes=30, tolerance_minutes=10)
        self.assertIn("turns round once, round a mapped loop at the end of a street", gen._caveat(easy, req.start, req))
        self.assertIn("doubles back once", gen._caveat(hard, req.start, req))


class MovingTests(_Base):
    def test_a_turn_back_waypoint_moves_to_the_easy_place(self):
        moved = steering.easier_turn_waypoints(route(spur(SPUR_END.lat), [SPUR_END]))
        self.assertEqual(moved, [Coord(lat=LOOP[0], lng=LOOP[1])])
        # Already at one: nothing to move.
        easy = route(spur(LOOP[0]), [Coord(lat=LOOP[0], lng=LOOP[1])])
        self.assertIsNone(steering.easier_turn_waypoints(easy))

    def test_the_moved_drive_is_offered_when_it_is_better(self):
        class Router:
            name = "fake"

            async def evaluate(self, start, finish, anchors, profile):
                return route(spur(anchors[0].lat), anchors, minutes=31.0)

        got = asyncio.run(steering.easier_turn_candidates(
            Router(), Coord(lat=52.0, lng=13.0), Coord(lat=52.0, lng=13.0),
            [route(spur(SPUR_END.lat), [SPUR_END])], "quiet"))
        self.assertEqual(len(got), 1)
        self.assertEqual(scorer.easy_turns(got[0]), ["loop"])


class NoPlacesTests(_Base):
    turns = []


class NotOpenToCarsTests(_Base):
    """A mapped place with no evidence the road is open to cars is a
    candidate only: no discount, no waypoint moved there (15 Oct 2026)."""
    turns = [[52.0327, 13.0, "loop", 16, 0]]

    def test_it_neither_counts_nor_draws_a_waypoint(self):
        self.assertIsNone(calming.easy_turn_at(52.0327, 13.0003))
        self.assertIsNone(steering.easier_turn_waypoints(route(spur(SPUR_END.lat), [SPUR_END])))

    def test_without_an_easy_place_nearby_nothing_moves(self):
        self.assertIsNone(steering.easier_turn_waypoints(route(spur(SPUR_END.lat), [SPUR_END])))


class TomTomTests(unittest.TestCase):
    def test_where_tomtom_asks_for_a_u_turn_is_kept(self):
        r = {"guidance": {"instructions": [
            {"maneuver": "TURN_LEFT", "point": {"latitude": 52.01, "longitude": 13.0}},
            {"maneuver": "MAKE_UTURN", "point": {"latitude": 52.03, "longitude": 13.0}}]}}
        self.assertEqual(R._uturn_points(r), [Coord(lat=52.03, lng=13.0)])


if __name__ == "__main__":
    unittest.main()

"""
Mapped speed bumps along a drive (docs/CALMER_DRIVES.md, 11 Oct 2026):
counted from prepared data, used in ranking without outranking the time, and
shown as "mapped", never as a promise of none.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from core import calming  # noqa: E402
from core.models import Coord, RoadMix  # noqa: E402
from core.router import EvaluatedRoute  # noqa: E402
from core import scorer  # noqa: E402

# A synthetic region and road, nobody's address: a straight road north
# along longitude 13.0, from 52.000 to 52.020 (about 2.2 km).
BBOX = [51.99, 12.99, 52.03, 13.01]
ROAD = [Coord(lat=52.0 + i * 0.001, lng=13.0) for i in range(21)]


def region(points):
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "test.json"), "w", encoding="utf-8") as f:
        json.dump({"region": "test", "bbox": BBOX, "as_of": "2026-10-11", "points": points}, f)
    return calming.load(d)


class CountTests(unittest.TestCase):
    def test_counts_bumps_on_the_road_and_not_beside_it(self):
        idx = region([
            [52.0055, 13.0, "hump"],           # on the road
            [52.0105, 13.00005, "table"],      # 3 m off the centre line
            [52.0155, 13.0, "cushion"],
            [52.0100, 13.0005, "hump"],        # about 34 m away: a side street
        ])
        b = calming.count_along(ROAD, idx)
        self.assertEqual(b.count, 3)
        self.assertGreater(b.covered_share, 0.99)
        self.assertAlmostEqual(b.covered_km, 2.22, places=1)

    def test_a_long_straight_segment_still_finds_its_bumps(self):
        idx = region([[52.010, 13.0, "hump"]])
        two_points = [ROAD[0], ROAD[-1]]                  # one 2.2 km segment
        self.assertEqual(calming.count_along(two_points, idx).count, 1)

    def test_a_bump_passed_twice_is_one_bump(self):
        idx = region([[52.005, 13.0, "hump"]])
        there_and_back = ROAD + ROAD[::-1]
        self.assertEqual(calming.count_along(there_and_back, idx).count, 1)

    def test_no_count_outside_the_prepared_data(self):
        idx = region([[52.005, 13.0, "hump"]])
        elsewhere = [Coord(lat=51.0 + i * 0.001, lng=0.0) for i in range(10)]
        self.assertIsNone(calming.count_along(elsewhere, idx))

    def test_no_count_when_most_of_the_drive_leaves_the_data(self):
        idx = region([[52.005, 13.0, "hump"]])
        mostly_out = ROAD[:3] + [Coord(lat=52.1 + i * 0.01, lng=13.0) for i in range(10)]
        self.assertIsNone(calming.count_along(mostly_out, idx))

    def test_no_data_at_all_is_no_count_not_an_error(self):
        self.assertIsNone(calming.count_along(ROAD, calming.load(tempfile.mkdtemp())))

    def test_the_prepared_windsor_data_is_readable_and_attributed(self):
        path = os.path.join(calming.DATA_DIR, "windsor.json")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual(d["attribution"], "© OpenStreetMap contributors")
        self.assertEqual(d["licence"], "ODbL 1.0")
        self.assertGreater(len(d["points"]), 1000)
        self.assertTrue(all(p[2] in calming_kinds() for p in d["points"]))


def calming_kinds():
    from tools.build_calming import VERTICAL
    return VERTICAL


def route(minutes, bumps_per_km=None, km=20.0):
    r = EvaluatedRoute(anchors=[], minutes=minutes, distance_km=km,
                       road_mix=RoadMix(secondary=0.5, residential=0.5), geometry=ROAD)
    r.bumps_checked = True
    r.bumps = (None if bumps_per_km is None else
               calming.BumpCount(count=round(bumps_per_km * km), covered_km=km, covered_share=1.0))
    return r


class RankingTests(unittest.TestCase):
    def test_among_drives_on_time_the_calmer_one_ranks_higher(self):
        calm, bumpy = route(30, 0.2), route(30, 2.0)
        self.assertGreater(scorer.score_route(calm, 30, "quiet"),
                           scorer.score_route(bumpy, 30, "quiet"))

    def test_time_still_comes_first(self):
        """A calm drive 10 minutes off never goes first over a bumpy one on
        time. The ranking decides, not the score alone: drives are ordered
        without bumps, and calmer_lead lets bumps change only first place,
        within CALM_SLACK_MIN of the time."""
        on_time_bumpy, late_calm = route(30, 3.0), route(40, 0.0)
        ranked = sorted([late_calm, on_time_bumpy],
                        key=lambda r: scorer.score_route(r, 30, "quiet", with_bumps=False),
                        reverse=True)
        self.assertIs(scorer.calmer_lead(ranked, 30, "quiet")[0], on_time_bumpy)

    def test_missing_data_is_neither_rewarded_nor_punished(self):
        unknown, typical = route(30, None), route(30, 0.7)
        self.assertAlmostEqual(scorer.score_route(unknown, 30, "mixed"),
                               scorer.score_route(typical, 30, "mixed"), places=3)

    def test_counted_once_per_route(self):
        r = EvaluatedRoute(anchors=[], minutes=30, distance_km=2.2,
                           road_mix=RoadMix(), geometry=ROAD)
        calls = []
        real = calming.count_along
        calming.count_along = lambda g, index=None: calls.append(1) or real(g, region([]))
        try:
            scorer.score_route(r, 30, "mixed")
            scorer.score_route(r, 30, "mixed")
        finally:
            calming.count_along = real
        self.assertEqual(len(calls), 1)


class CalmerLeadTests(unittest.TestCase):
    """Fewer bumps never at the cost of a turn-around or the time (measured
    on 160 real candidates, 11 Oct 2026: a plain penalty bought both)."""

    def ranked(self, *routes):
        return scorer.calmer_lead(list(routes), 30, "mixed")

    def test_a_calmer_drive_as_good_otherwise_goes_first(self):
        bumpy, calm = route(31, 2.0), route(32, 0.1)
        self.assertIs(self.ranked(bumpy, calm)[0], calm)

    def test_not_if_it_adds_a_turn_around(self):
        bumpy, calm = route(31, 2.0), route(31, 0.1)
        orig = scorer.turnaround_count
        scorer.turnaround_count = lambda r: 1 if r is calm else 0
        try:
            self.assertIs(self.ranked(bumpy, calm)[0], bumpy)
        finally:
            scorer.turnaround_count = orig

    def test_not_if_it_lands_much_further_from_the_time(self):
        bumpy, calm = route(31, 2.0), route(36, 0.0)       # 5 minutes worse
        self.assertIs(self.ranked(bumpy, calm)[0], bumpy)

    def test_only_first_place_changes(self):
        a, b, c = route(30, 2.0), route(31, 1.5), route(31, 0.0)
        self.assertEqual(self.ranked(a, b, c), [c, a, b])


class ApiTests(unittest.TestCase):
    def test_every_drive_says_its_count_or_nothing(self):
        from test_identity_auth0 import _fresh
        client, _ = _fresh(configured=False)
        try:
            r = client.post("/api/generate", json={
                "start": {"lat": 51.4857, "lng": -0.6214}, "target_minutes": 30})
            self.assertEqual(r.status_code, 200, r.text)
            for opt in r.json()["routes"]:
                self.assertIn("speed_bumps", opt)
                # The test server uses the simulator: invented geometry gets no count.
                if opt["simulated"]:
                    self.assertIsNone(opt["speed_bumps"])
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()

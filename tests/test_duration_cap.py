"""
The first drive's time bound (scorer.FIRST_EXTRA_MIN; founder and Astra
brief, 15 Oct 2026, an experiment): whatever ranks a drive first, it lands
at most two minutes further from the time asked than the closest-to-time
eligible candidate, judged on each candidate's final routed duration. A
materially calmer drive beyond that stays on offer, labelled with what it
trades.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from core import calming, scorer  # noqa: E402
from core.models import Coord, GenerateRequest, RoadMix  # noqa: E402
from core.router import EvaluatedRoute  # noqa: E402


def route(minutes, bumps=0, lights=0, turns=0, km=20.0):
    r = EvaluatedRoute(anchors=[], minutes=minutes, distance_km=km, road_mix=RoadMix(),
                       geometry=[Coord(lat=52.0, lng=13.0), Coord(lat=52.1, lng=13.0)], works=[])
    r.bumps = calming.BumpCount(count=bumps, covered_km=km, covered_share=1.0)
    r.lights = calming.LightCount(junctions=lights, pedestrian=0, covered_km=km)
    r.bumps_checked = r.lights_checked = True
    r.__dict__["_turns"] = turns
    return r


class _Turns(unittest.TestCase):
    def setUp(self):
        self.real = scorer.turnaround_count
        scorer.turnaround_count = lambda r: r.__dict__.get("_turns", 0)

    def tearDown(self):
        scorer.turnaround_count = self.real


class ArrivalWindowTests(_Turns):
    """Arrive by a time (founder's drive, 21 Oct 2026): every drive in the
    window arrives in time, so the calmest of them may go first, however far
    from the internal aim."""

    def test_the_calmest_drive_that_arrives_in_time_goes_first(self):
        on_aim, twice_back, calm = route(65, bumps=20), route(63, bumps=19, turns=2), route(61, bumps=2)
        ranked = [twice_back, on_aim, calm]
        # By length, 61 is beyond two minutes of the closest (65): not first.
        self.assertIs(scorer.calmer_lead(ranked, 65, "mixed")[0], twice_back)
        # Arriving by a time, 60 to 70 minutes all arrive in time.
        self.assertIs(scorer.calmer_lead(ranked, 65, "mixed", (60, 70))[0], calm)

    def test_a_leader_outside_the_window_gives_way(self):
        early, in_time = route(55, bumps=0), route(66, bumps=5)
        self.assertIs(scorer.first_within_time([early, in_time], 65, (60, 70))[0], in_time)

    def test_the_note_speaks_of_arriving(self):
        lead, calm = route(63, bumps=19, turns=2), route(61, bumps=2)
        note = scorer.tradeoff_note(calm, lead, 65, latest=70)
        self.assertIn("2 min shorter, so you'd arrive that much earlier", note)
        self.assertNotIn("65", note)


class BoundTests(_Turns):
    def test_a_leader_far_from_the_time_gives_way_to_one_within_two_minutes(self):
        smooth_but_late, on_time = route(38), route(30.5)
        ranked = scorer.first_within_time([smooth_but_late, on_time], 30)
        self.assertIs(ranked[0], on_time)
        self.assertIn(smooth_but_late, ranked)          # kept, not dropped

    def test_shorter_and_longer_with_equal_error_are_both_within_it(self):
        short, long_ = route(28), route(32)
        self.assertIs(scorer.first_within_time([long_, short], 30)[0], long_)
        self.assertIs(scorer.first_within_time([short, long_], 30)[0], short)

    def test_a_calmer_drive_within_the_cap_still_goes_first(self):
        bumpy, calm = route(30, bumps=12), route(31.9, bumps=1)
        self.assertIs(scorer.calmer_lead([bumpy, calm], 30, "mixed")[0], calm)

    def test_a_much_calmer_drive_beyond_the_cap_does_not(self):
        bumpy, calm = route(30, bumps=12), route(32.5, bumps=0)
        self.assertIs(scorer.calmer_lead([bumpy, calm], 30, "mixed")[0], bumpy)

    def test_the_bound_never_widens_the_tolerance_window(self):
        # Every candidate far off: the first is the closest, not one "within
        # two minutes" of an imaginary on-time drive.
        far, farther = route(42), route(45)
        self.assertIs(scorer.first_within_time([farther, far], 30)[0], far)

    def test_no_candidates_no_drive(self):
        self.assertEqual(scorer.first_within_time([], 30), [])
        self.assertEqual(scorer.calmer_lead([], 30, "mixed"), [])


class TradeoffTests(_Turns):
    def test_an_alternative_says_what_it_gains_and_gives_up_kind_by_kind(self):
        lead = route(30, bumps=10, lights=2, turns=0)
        calm = route(35, bumps=1, lights=4, turns=1)
        note = scorer.tradeoff_note(calm, lead, 30)
        self.assertIn("9 fewer speed bumps", note)
        self.assertIn("2 more sets of lights", note)
        self.assertIn("1 more turn-around", note)
        self.assertIn("about 5 min further from your 30 min", note)

    def test_no_label_unless_materially_calmer(self):
        lead = route(30, bumps=3)
        self.assertIsNone(scorer.tradeoff_note(route(31, bumps=2), lead, 30))
        self.assertIsNone(scorer.tradeoff_note(lead, lead, 30))


class PickTests(_Turns):
    def pick(self, routes):
        import importlib
        gen = importlib.import_module("core.generator")
        req = gen.GenerateRequest(start=gen.Coord(lat=52.0, lng=13.0), target_minutes=30, tolerance_minutes=10)
        with unittest.mock.patch.dict(gen.__dict__, {"passes_validation": lambda ev, f: True}):
            return gen._pick_top_three(routes, req.start, req, "mixed")

    def test_the_calmest_beyond_the_cap_stays_among_the_three(self):
        import unittest.mock  # noqa: F401
        a, b, c = route(30, bumps=10, km=20), route(30.5, bumps=10, km=24), route(31, bumps=9, km=28)
        calm = route(36, bumps=0, km=33)
        top = self.pick([a, b, c, calm])
        self.assertLessEqual(abs(top[0].minutes - 30), 2)
        self.assertIn(calm, top)

    def test_a_moved_waypoint_is_judged_on_its_own_new_duration(self):
        import unittest.mock  # noqa: F401
        # Before the move the drive was on time; the moved one (a new
        # evaluation) came back 6 minutes long: it cannot lead.
        before = route(30, bumps=6, turns=1, km=20)
        moved = route(36, bumps=6, turns=0, km=26)
        top = self.pick([before, moved])
        self.assertIs(top[0], before)


if __name__ == "__main__":
    unittest.main()

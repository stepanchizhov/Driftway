"""
Pram and carrier assessment.

The failure modes these guard against, worst first:

  * a blocking obstacle averaged away by the pleasant stretch around it
  * "not recorded" quietly treated as fine - an unknown surface counted as ok,
    a gate with no recorded width counted as passable
  * the same evidence giving the same answer for a pram and a carrier, when
    steps stop one and barely matter to the other
  * an out-and-back that forgets the return leg climbs what the outward leg
    descended

Pure logic: no network, no database, no curated files.
"""

import os
import sys
import unittest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from core.walking.catalogue import Route, assess_route  # noqa: E402
from core.walking.evidence import (  # noqa: E402
    Barrier, BarrierKind, Evidence, Gradient, Section, Status, Surface,
)
from core.walking.osm import (  # noqa: E402
    access_forbidden, parse_width_cm, steps_barrier, surface_from_tags,
)
from core.walking.profiles import (  # noqa: E402
    CarrierSetup, PramSetup, Verdict, assess_carrier, assess_pram,
)


def section(from_m=0, to_m=200, surface=Surface.SEALED, *, barriers=(),
            gradient=None, evidence=None, label="test"):
    s = Section(from_m=from_m, to_m=to_m, label=label, geometry=[],
                surface=surface, barriers=list(barriers), gradient=gradient)
    if evidence is None and surface is not Surface.UNKNOWN:
        evidence = [Evidence("surface", surface.value, Status.MAPPED, "osm:way/1")]
    s.evidence = evidence or []
    return s


def steps(at_m=100, ramp=None, count=None):
    return Barrier(BarrierKind.STEPS, at_m, Status.MAPPED, "osm:way/9",
                   step_count=count, has_ramp=ramp)


def gate(at_m=100, width=None, kind=BarrierKind.GATE):
    return Barrier(kind, at_m, Status.MAPPED, "osm:node/5", width_cm=width)


def route(*sections, shape="loop"):
    return Route(id="t", name="Test", area="", summary="", shape=shape,
                 start={"lat": 0, "lng": 0, "label": "x"},
                 sections=list(sections), sources=[], built_on="2026-10-08")


# ------------------------------------------------------------ OSM tags

class OsmTranslationTests(unittest.TestCase):
    def test_known_surfaces_map_to_how_they_ride(self):
        self.assertEqual(surface_from_tags({"surface": "asphalt"}, "s")[0], Surface.SEALED)
        self.assertEqual(surface_from_tags({"surface": "sett"}, "s")[0], Surface.SETTS)
        self.assertEqual(surface_from_tags({"surface": "gravel"}, "s")[0], Surface.LOOSE)
        self.assertEqual(surface_from_tags({"surface": "grass"}, "s")[0], Surface.SOFT)

    def test_an_untagged_path_has_no_surface_evidence_at_all(self):
        """The 75% case in central Windsor. Nothing must be invented for it."""
        cls, evidence = surface_from_tags({"highway": "footway"}, "s")
        self.assertEqual(cls, Surface.UNKNOWN)
        self.assertEqual(evidence, [])

    def test_an_unrecognised_value_is_kept_but_classed_unknown(self):
        cls, evidence = surface_from_tags({"surface": "bouncy_castle"}, "s")
        self.assertEqual(cls, Surface.UNKNOWN)
        self.assertEqual(evidence[0].value, "bouncy_castle")

    def test_widths_are_metres_unless_stated(self):
        self.assertEqual(parse_width_cm("1.2"), 120)
        self.assertEqual(parse_width_cm("90 cm"), 90)
        self.assertIsNone(parse_width_cm("narrow"))
        self.assertIsNone(parse_width_cm(None))

    def test_foot_overrides_access(self):
        """Closed to vehicles, open on foot - OSM's usual way of saying so."""
        self.assertFalse(access_forbidden({"access": "no", "foot": "yes"}))
        self.assertTrue(access_forbidden({"access": "private"}))
        self.assertTrue(access_forbidden({"foot": "no"}))

    def test_steps_ramp_is_read_most_specific_first(self):
        b = steps_barrier({"ramp": "no", "ramp:stroller": "yes", "step_count": "12"}, 0, "s")
        self.assertTrue(b.has_ramp)
        self.assertEqual(b.step_count, 12)
        self.assertIsNone(steps_barrier({}, 0, "s").has_ramp)


# ----------------------------------------------------------------- pram

class PramTests(unittest.TestCase):
    def test_steps_without_a_ramp_block_a_pram(self):
        a = assess_pram(section(barriers=[steps(count=15)]), PramSetup())
        self.assertEqual(a.verdict, Verdict.BLOCKED)
        self.assertIn("15 steps", a.findings[0].reason)

    def test_steps_with_a_mapped_ramp_are_difficult_not_blocked(self):
        a = assess_pram(section(barriers=[steps(ramp=True)]), PramSetup())
        self.assertEqual(a.verdict, Verdict.DIFFICULT)

    def test_a_stile_blocks_a_pram(self):
        a = assess_pram(section(barriers=[gate(kind=BarrierKind.STILE)]), PramSetup())
        self.assertEqual(a.verdict, Verdict.BLOCKED)

    def test_a_gate_of_unknown_width_is_unknown_not_passable(self):
        """Missing gate width is not proof of access."""
        a = assess_pram(section(barriers=[gate(width=None)]), PramSetup(width_cm=60))
        self.assertEqual(a.verdict, Verdict.UNKNOWN)

    def test_a_gate_known_to_be_too_narrow_blocks(self):
        a = assess_pram(section(barriers=[gate(width=65)]), PramSetup(width_cm=60))
        self.assertEqual(a.verdict, Verdict.BLOCKED)

    def test_a_gate_known_to_be_wide_enough_says_nothing(self):
        a = assess_pram(section(barriers=[gate(width=120)]), PramSetup(width_cm=60))
        self.assertEqual(a.verdict, Verdict.OK)

    def test_an_unknown_surface_is_unknown_not_ok(self):
        a = assess_pram(section(surface=Surface.UNKNOWN), PramSetup())
        self.assertEqual(a.verdict, Verdict.UNKNOWN)

    def test_setts_matter_for_small_wheels_and_are_a_note_otherwise(self):
        small = assess_pram(section(surface=Surface.SETTS), PramSetup(wheels="compact"))
        sturdy = assess_pram(section(surface=Surface.SETTS), PramSetup(wheels="standard"))
        self.assertEqual(small.verdict, Verdict.DIFFICULT)
        self.assertEqual(sturdy.verdict, Verdict.OK)
        self.assertTrue(sturdy.findings[0].preference)

    def test_loose_ground_depends_on_the_wheels(self):
        self.assertEqual(assess_pram(section(surface=Surface.LOOSE),
                                     PramSetup(wheels="all_terrain")).verdict, Verdict.OK)
        self.assertEqual(assess_pram(section(surface=Surface.LOOSE),
                                     PramSetup(wheels="standard")).verdict,
                         Verdict.DIFFICULT)

    def test_a_steep_descent_is_flagged_not_just_a_climb(self):
        g = Gradient(0, 20, 0, 11, Status.MODELLED, "eudem25m")
        a = assess_pram(section(gradient=g), PramSetup())
        self.assertEqual(a.verdict, Verdict.DIFFICULT)
        self.assertIn("holding back", a.findings[0].reason)

    def test_a_narrow_path_blocks_a_wide_pram(self):
        ev = [Evidence("surface", "asphalt", Status.MAPPED, "s"),
              Evidence("width_cm", 55, Status.MAPPED, "s")]
        a = assess_pram(section(evidence=ev), PramSetup(width_cm=60))
        self.assertEqual(a.verdict, Verdict.BLOCKED)


# -------------------------------------------------------------- carrier

class CarrierTests(unittest.TestCase):
    def test_steps_do_not_stop_a_carrier(self):
        a = assess_carrier(section(barriers=[steps(count=15)]), CarrierSetup())
        self.assertEqual(a.verdict, Verdict.OK)

    def test_a_stile_is_difficult_with_a_child_on_you(self):
        a = assess_carrier(section(barriers=[gate(kind=BarrierKind.STILE)]), CarrierSetup())
        self.assertEqual(a.verdict, Verdict.DIFFICULT)

    def test_loose_ground_on_a_slope_is_about_footing(self):
        g = Gradient(15, 0, 9, 0, Status.MODELLED, "eudem25m")
        a = assess_carrier(section(surface=Surface.LOOSE, gradient=g), CarrierSetup())
        self.assertEqual(a.verdict, Verdict.DIFFICULT)
        self.assertTrue(any("footing" in f.reason for f in a.findings))

    def test_luggage_carried_by_a_companion_is_not_the_carriers_load(self):
        mine = CarrierSetup(child_kg=9, carrier_kg=1.2, luggage_kg=4)
        theirs = CarrierSetup(child_kg=9, carrier_kg=1.2, luggage_kg=4,
                              luggage_with="companion")
        self.assertEqual(mine.carried_kg(), 14.2)
        self.assertEqual(theirs.carried_kg(), 10.2)

    def test_an_unknown_part_of_the_load_is_not_guessed(self):
        self.assertIsNone(CarrierSetup(child_kg=9).carried_kg())


# ---------------------------------------------------------------- routes

class RouteTests(unittest.TestCase):
    def test_one_blocked_section_is_not_averaged_away(self):
        """Two kilometres of lovely path do not dilute one flight of steps."""
        r = route(section(0, 1000), section(1000, 1010, barriers=[steps(1005)]),
                  section(1010, 2000))
        card = assess_route(r, "pram", PramSetup())
        self.assertEqual(card["verdict"], "blocked")
        self.assertEqual(len(card["blocking"]), 1)

    def test_the_same_route_differs_for_pram_and_carrier(self):
        r = route(section(0, 500, barriers=[steps(250, count=20)]))
        self.assertEqual(assess_route(r, "pram", PramSetup())["verdict"], "blocked")
        self.assertEqual(assess_route(r, "carrier", CarrierSetup())["verdict"], "ok")

    def test_a_route_of_unknown_surfaces_is_unknown_not_ok(self):
        r = route(section(0, 800, surface=Surface.UNKNOWN))
        card = assess_route(r, "pram", PramSetup())
        self.assertEqual(card["verdict"], "unknown")
        self.assertEqual(card["coverage"]["surface_known_share"], 0)

    def test_out_and_back_climbs_on_the_way_back_what_it_descended(self):
        down = Gradient(0, 25, 0, 9, Status.MODELLED, "eudem25m")
        r = route(section(0, 600, gradient=down), shape="out_and_back")
        card = assess_route(r, "pram", PramSetup())
        self.assertEqual(card["distance_m"], 1200)
        self.assertEqual(card["ascent_m"], 25)
        reasons = " ".join(f["reason"] for f in card["difficult"])
        self.assertIn("descent", reasons)
        self.assertIn("climb", reasons)

    def test_out_and_back_reports_an_obstacle_once(self):
        r = route(section(0, 600, barriers=[gate(300)]), shape="out_and_back")
        card = assess_route(r, "pram", PramSetup(width_cm=60))
        self.assertEqual(len([f for f in card["unknowns"] if f["kind"] == "barrier"]), 1)

    def test_time_states_its_assumptions(self):
        card = assess_route(route(section(0, 2000)), "pram", PramSetup())
        self.assertEqual(card["minutes"], 30)        # 2 km at 4 km/h
        self.assertIn("4 km/h", card["assumptions"])
        self.assertIn("No stops", card["assumptions"])

    def test_ascent_is_unknown_rather_than_zero_without_a_model(self):
        """The 2.11 km / 0 m screenshot: zero ascent must not mean flat."""
        card = assess_route(route(section(0, 2000)), "pram", PramSetup())
        self.assertIsNone(card["ascent_m"])
        self.assertEqual(card["coverage"]["gradient"], "unknown")

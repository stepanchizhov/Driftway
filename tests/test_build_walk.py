"""
The walk builder's privacy trim, and one-way walks.

The trim exists because walk files are committed to a public repository and
shown to every beta tester, while some walks are routes from someone's home.
It must remove every coordinate of the opening stretch, not just move the
label. No network: these exercise the pure parts of the builder.
"""

import os
import sys
import unittest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from core.walking.catalogue import Route, assess_route  # noqa: E402
from core.walking.evidence import Barrier, BarrierKind, Section, Status, Surface  # noqa: E402
from core.walking.profiles import PramSetup  # noqa: E402
from tools.build_walk import _trim_start, haversine  # noqa: E402

# A straight line north, 1 km long, points every 100 m (about 0.0009 deg).
LINE = [[52.0 + i * 0.000899, 13.0] for i in range(11)]
HOME = (52.0, 13.0)


def walk():
    a = Section(0, 500, "Home street", LINE[:6], surface=Surface.SEALED)
    b = Section(500, 1000, "Path", LINE[5:], surface=Surface.SOFT)
    b.barriers.append(Barrier(BarrierKind.GATE, 800, Status.MAPPED, "osm:node/1"))
    return [a, b]


class TrimTests(unittest.TestCase):
    def test_no_coordinate_of_the_opening_stretch_survives(self):
        trimmed = _trim_start(walk(), 400)
        nearest = min(haversine(HOME, tuple(p)) for s in trimmed for p in s.geometry)
        self.assertGreaterEqual(nearest, 395)

    def test_distances_restart_from_the_new_start(self):
        trimmed = _trim_start(walk(), 400)
        self.assertEqual(trimmed[0].from_m, 0)
        self.assertAlmostEqual(trimmed[-1].to_m, 600)

    def test_barriers_keep_their_place_relative_to_the_new_start(self):
        trimmed = _trim_start(walk(), 400)
        self.assertEqual(trimmed[-1].barriers[0].at_m, 400)

    def test_the_named_home_street_is_dropped_when_fully_trimmed(self):
        labels = {s.label for s in _trim_start(walk(), 600)}
        self.assertNotIn("Home street", labels)

    def test_trimming_the_whole_walk_is_refused(self):
        with self.assertRaises(RuntimeError):
            _trim_start(walk(), 1200)


class OneWayTests(unittest.TestCase):
    def route(self, length=4000):
        s = Section(0, length, "Path", [], surface=Surface.SEALED)
        return Route(id="w", name="To the lake", area="", summary="",
                     shape="one_way", start={"lat": 0, "lng": 0, "label": ""},
                     sections=[s], sources=[], built_on="2026-10-09")

    def test_a_one_way_walk_is_not_doubled(self):
        card = assess_route(self.route(), "pram", PramSetup(), minutes=60)
        self.assertEqual(card["distance_m"], 4000)
        self.assertEqual(card["minutes"], 60)

    def test_a_one_way_walk_is_not_shortened_by_turning_back(self):
        fit = assess_route(self.route(6000), "pram", PramSetup(), minutes=60)["fit"]
        self.assertEqual(fit["kind"], "longer")
        self.assertFalse(fit["can_shorten"])

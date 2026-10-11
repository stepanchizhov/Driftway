"""
Walking routes mapped in OpenStreetMap, turned into curated walks
(tools/import_osm_routes.py, tools/build_walk.py; 11 Oct 2026). Synthetic
data only: no network.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from tools.build_walk import Graph, _walk_from_relation, osgb_to_wgs84  # noqa: E402
from tools.import_osm_routes import faithful, spec_for  # noqa: E402


def node(i):
    # A 3 x 3 grid of nodes about 110 m apart; nobody's address.
    return 52.0 + (i // 3) * 0.001, 13.0 + (i % 3) * 0.0016


def way(wid, nodes, **tags):
    tags.setdefault("highway", "footway")
    return {"type": "way", "id": wid, "nodes": nodes, "tags": tags,
            "geometry": [{"lat": node(n)[0], "lon": node(n)[1]} for n in nodes]}


# A square loop 0-1-2-5-8-7-6-3-0 as four ways, plus the middle node 4 joined
# to 1 and 7 so there is another way round.
WAYS = [way(10, [0, 1, 2]), way(11, [2, 5, 8]), way(12, [8, 7, 6]), way(13, [6, 3, 0]),
        way(14, [1, 4, 7])]


def graph():
    return Graph({"elements": WAYS})


def relation(members, roundtrip="yes", extra_ways=()):
    ways = {w["id"]: w for w in list(WAYS) + list(extra_ways)}
    return {"relation": {"tags": {"roundtrip": roundtrip},
                         "members": [{"type": "way", "ref": m, "role": ""} for m in members]},
            "ways": ways, "osm_base": "test"}


class GridReferenceTests(unittest.TestCase):
    def test_the_ordnance_survey_worked_example(self):
        lat, lng = osgb_to_wgs84("TG 51409 13177")      # 52.65798 N, 1.71605 E
        self.assertAlmostEqual(lat, 52.65798, places=4)
        self.assertAlmostEqual(lng, 1.71605, places=4)

    def test_not_a_grid_reference(self):
        for bad in ("shortens.drummers.cloak", "SU12345", "12345678", ""):
            self.assertIsNone(osgb_to_wgs84(bad), bad)


class ChainTests(unittest.TestCase):
    def nodes(self, rel, start_near=None):
        pts, notes = _walk_from_relation(graph(), rel, start_near)
        coords = [p[0] for p in pts]
        return [min(range(9), key=lambda i: abs(node(i)[0] - c[0]) + abs(node(i)[1] - c[1]))
                for c in coords], notes

    def test_members_mapped_the_other_way_are_turned_round(self):
        rev = [way(10, [2, 1, 0]), way(11, [8, 5, 2]), way(12, [6, 7, 8]), way(13, [0, 3, 6])]
        seq, notes = self.nodes(relation([10, 11, 12, 13], extra_ways=rev))
        self.assertEqual(seq, [0, 1, 2, 5, 8, 7, 6, 3, 0])
        self.assertEqual(notes, [])

    def test_car_parks_and_cafes_listed_as_members_are_not_walked(self):
        # A car park beside corner 8: not walked, but the loop starts there.
        lat, lng = node(8)
        car_park = {"type": "way", "id": 90, "nodes": [100, 101], "tags": {"amenity": "parking"},
                    "geometry": [{"lat": lat + 0.0002, "lon": lng}, {"lat": lat + 0.0003, "lon": lng}]}
        seq, _ = self.nodes(relation([10, 90, 11, 12, 13], extra_ways=[car_park]))
        self.assertEqual(seq, [8, 7, 6, 3, 0, 1, 2, 5, 8])

    def test_a_gap_is_walked_round_on_mapped_paths_and_said(self):
        seq, notes = self.nodes(relation([10, 12, 13]))          # 11 missing
        self.assertEqual(seq[:3], [0, 1, 2])
        self.assertIn(8, seq)                                     # reached by other mapped paths
        self.assertTrue(any("don't join" in n for n in notes))

    def test_a_loop_starts_near_its_named_start(self):
        seq, _ = self.nodes(relation([10, 11, 12, 13]), start_near=node(8))
        self.assertEqual(seq[0], 8)
        self.assertEqual(seq[-1], 8)
        self.assertEqual(len(seq), 9)


class GateTests(unittest.TestCase):
    def test_a_faithful_build_passes(self):
        self.assertEqual(faithful(3.1, 3.0, 2.6, ["has 2 places where its paths don't join"]), "")

    def test_too_many_gaps_are_held(self):
        self.assertIn("28 places", faithful(6.3, 2.0, 3.7, ["The mapped trail has 28 places where its paths don't join or can't be used"]))

    def test_going_round_gaps_must_not_add_much(self):
        self.assertIn("adds too much", faithful(2.2, 0.8, 1.5, []))

    def test_a_trail_mostly_missing_from_the_map_is_held(self):
        self.assertIn("only 2.0 km", faithful(2.1, 2.0, 5.9, []))


class SpecTests(unittest.TestCase):
    def test_facts_are_kept_and_the_description_is_not_copied(self):
        spec = spec_for({"id": 1, "tags": {
            "name": "Blue Trail, Somewhere", "operator": "National Trust", "distance": "2.6",
            "duration": "00:45", "roundtrip": "yes",
            "from": "Woodland car park, Somewhere, Town, AB1 2CD;TG5140913177",
            "website": "https://example.org/blue", "description": "Lovely words, copied."}})
        self.assertEqual(spec["name"], "Blue Trail")
        self.assertEqual(spec["area"], "Somewhere")
        self.assertEqual(spec["start_label"], "Woodland car park, Somewhere")
        self.assertAlmostEqual(spec["start_near"][0], 52.658, places=2)
        self.assertNotIn("Lovely words", str(spec))
        self.assertTrue(any("https://example.org/blue" in n for n in spec["notes"]))
        self.assertTrue(any("45 minutes" in n for n in spec["notes"]))


if __name__ == "__main__":
    unittest.main()

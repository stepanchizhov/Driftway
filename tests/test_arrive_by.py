"""
Drives planned by an arrival time (founder, 18 Oct 2026: "we need to be
there at 10.55"). The app sends the minutes until then with arrive_by: no
drive offered may take longer, and they aim a few minutes early. Fake
routers only, no network.
"""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from backend.core.generator import arrive_margin, generate_routes  # noqa: E402
from backend.core.geometry import haversine_km  # noqa: E402
from backend.core.models import Coord, Direction, GenerateRequest, RoadProfile  # noqa: E402
from backend.core.router import EvaluatedRoute  # noqa: E402
from test_route_modes import FAR, MIX, POOL, ScaledRouter, _geometry  # noqa: E402


class KmRouter:
    """Two minutes a kilometre, whatever the shape: a loop's time follows
    its size, so the generator can aim at any length."""

    name = "test-km"

    async def evaluate(self, start, finish, anchors, profile):
        pts = [start, *anchors, finish]
        km = sum(haversine_km(a, b) for a, b in zip(pts, pts[1:]))
        geometry = []
        for a, b in zip(pts, pts[1:]):
            geometry.extend(_geometry(a, b, 12))
        return EvaluatedRoute(anchors=anchors, minutes=round(km * 2.0, 1), distance_km=round(km, 1),
                              road_mix=MIX, geometry=geometry)


def _req(start, finish, minutes, arrive_by=True):
    return GenerateRequest(start=start, finish=finish, target_minutes=minutes, tolerance_minutes=10,
                           road_profile=RoadProfile.MIXED, direction=Direction.SURPRISE, arrive_by=arrive_by)


class ArriveByTests(unittest.TestCase):
    def test_the_margin_is_a_few_minutes(self):
        self.assertEqual([arrive_margin(m) for m in (10, 30, 40, 60, 120)], [2, 2, 3, 5, 5])

    def test_no_loop_comes_back_late(self):
        res = asyncio.run(generate_routes(_req(POOL, POOL, 40), KmRouter()))
        self.assertTrue(res.routes)
        self.assertEqual(res.target_minutes, 40)              # the time there is, as asked
        for r in res.routes:
            self.assertLessEqual(r.predicted_minutes, 40)
        # The same request by length may offer longer drives: ±10 minutes.
        by_length = asyncio.run(generate_routes(_req(POOL, POOL, 40, arrive_by=False), KmRouter()))
        self.assertTrue(by_length.routes)

    def test_too_little_time_for_a_longer_drive_gives_the_direct_way(self):
        # Direct takes 25 minutes; 26 minutes there: no room for a detour.
        res = asyncio.run(generate_routes(_req(POOL, FAR, 26), ScaledRouter(direct_minutes=25.0)))
        self.assertEqual(len(res.routes), 1)
        self.assertTrue(res.routes[0].is_direct)
        self.assertIn("leaves no time for a longer drive", res.notice)

    def test_not_even_the_direct_way_in_time_says_so(self):
        res = asyncio.run(generate_routes(_req(POOL, FAR, 20), ScaledRouter(direct_minutes=25.0)))
        self.assertTrue(res.routes[0].is_direct)
        self.assertIn("longer than the 20 minutes there are", res.notice)

    def test_a_drive_with_time_to_spare_still_arrives_in_time(self):
        res = asyncio.run(generate_routes(_req(POOL, FAR, 45), ScaledRouter(direct_minutes=25.0)))
        self.assertTrue(res.routes)
        for r in res.routes:
            self.assertLessEqual(r.predicted_minutes, 45)
        # By length, 45 minutes may mean a few more: here it does.
        by_length = asyncio.run(generate_routes(_req(POOL, FAR, 45, arrive_by=False),
                                                ScaledRouter(direct_minutes=25.0)))
        self.assertGreater(max(r.predicted_minutes for r in by_length.routes), 45)


if __name__ == "__main__":
    unittest.main()

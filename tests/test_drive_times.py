"""
Drive times (founder, 23 Oct 2026: "I was getting to the destination a bit
too early"). TomTom adds a fixed two minutes for every turn-round
(tools/time_check.py --uturns: 2.0 to 2.1 min at 8 of 8 points, Google
none); Driftway counts a real turn of about half a minute instead.
No network: a fake TomTom.
"""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import httpx  # noqa: E402

import test_identity_auth0  # noqa: E402,F401  (puts backend/ on the path)

from core import router as R  # noqa: E402
from core.models import Coord  # noqa: E402

HERE = Coord(lat=51.4834, lng=-0.6105)
THERE = Coord(lat=51.4950, lng=-0.6300)


def answer(turns):
    instructions = [{"maneuver": "DEPART", "point": {"latitude": 51.48, "longitude": -0.61}}]
    instructions += [{"maneuver": "MAKE_UTURN", "point": {"latitude": 51.49, "longitude": -0.62}}] * turns
    return {"routes": [{"summary": {"travelTimeInSeconds": 1800, "lengthInMeters": 15000},
                        "legs": [], "guidance": {"instructions": instructions}}]}


class TurnRoundTests(unittest.TestCase):
    def setUp(self):
        R._tomtom_down_until = 0.0

    def minutes(self, turns):
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda q: httpx.Response(200, json=answer(turns))))
        ev = asyncio.run(R.TomTomRouter("tt", client=client).evaluate(HERE, HERE, [THERE], "mixed"))
        return ev.minutes

    def test_a_drive_without_turning_round_keeps_tomtoms_time(self):
        self.assertEqual(self.minutes(0), 30.0)

    def test_each_turn_round_counts_half_a_minute_not_two(self):
        self.assertEqual(self.minutes(1), 28.5)
        self.assertEqual(self.minutes(2), 27.0)


if __name__ == "__main__":
    unittest.main()

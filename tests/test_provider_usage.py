"""
Provider calls counted per API and operation, and Driftway's own daily
ceilings for TomTom's APIs (core/usage.py; founder and Astra brief, 15 Oct
2026). No network.
"""

import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import httpx  # noqa: E402

REAL_CLIENT = httpx.AsyncClient


def usage():
    import importlib
    return importlib.import_module("core.usage")


class CountingTests(unittest.TestCase):
    def setUp(self):
        usage().reset()

    def test_calls_are_counted_per_api_and_operation_and_per_drive(self):
        u = usage()
        with u.operation("drive"):
            for _ in range(3):
                u.spend("tomtom.routing")
            u.spend("tomtom.incidents")
        with u.operation("walk"):
            u.record("ors.directions")
        s = u.summary()
        self.assertEqual(s["calls_by_api"], {"tomtom.routing": 3, "tomtom.incidents": 1, "ors.directions": 1})
        self.assertEqual(s["calls_by_operation"]["drive"], {"tomtom.routing": 3, "tomtom.incidents": 1})
        self.assertEqual(s["per_drive_request"]["tomtom.routing"], {"min": 3, "median": 3, "max": 3})

    def test_each_api_has_its_own_ceiling(self):
        u = usage()
        with mock.patch.dict(os.environ, {"TOMTOM_ROUTING_PER_DAY": "2"}):
            self.assertTrue(u.spend("tomtom.routing"))
            self.assertTrue(u.spend("tomtom.routing"))
            self.assertFalse(u.spend("tomtom.routing"))
            self.assertTrue(u.spend("tomtom.search"))          # a separate pool
        self.assertEqual(u.summary()["not_made_at_ceiling"], {"tomtom.routing": 1})


class CeilingBehaviourTests(unittest.TestCase):
    def setUp(self):
        usage().reset()
        from core import router as R
        R._tomtom_down_until = 0.0

    def tearDown(self):
        from core import router as R
        R._tomtom_down_until = 0.0

    def test_at_the_ceiling_drives_stand_tomtom_down_without_calling_it(self):
        from core import router as R
        seen = []
        tomtom = R.TomTomRouter("tt", client=REAL_CLIENT(transport=httpx.MockTransport(
            lambda r: seen.append(r) or httpx.Response(500))))
        from core.models import Coord
        with mock.patch.dict(os.environ, {"TOMTOM_ROUTING_PER_DAY": "0"}):
            out = asyncio.run(tomtom.evaluate(Coord(lat=52, lng=13), Coord(lat=52, lng=13), [], "mixed"))
        self.assertIsNone(out)
        self.assertEqual(seen, [])
        self.assertFalse(R.tomtom_available())                  # the fallback takes over

    def test_at_the_ceiling_roadworks_are_not_checked_rather_than_none(self):
        from core import incidents
        incidents.reset_cache()
        with mock.patch.dict(os.environ, {"TOMTOM_INCIDENTS_PER_DAY": "0", "TOMTOM_API_KEY": "tt"}):
            self.assertIsNone(asyncio.run(incidents.fetch(51.9, 12.9, 52.1, 13.1)))


class EndpointTests(unittest.TestCase):
    def test_the_founder_sees_the_counts_and_nobody_else_does(self):
        from test_identity_auth0 import _fresh
        client, _ = _fresh(configured=False)
        try:
            with mock.patch.dict(os.environ, {"ADMIN_API_TOKEN": "founder"}):
                self.assertEqual(client.get("/api/admin/provider-usage").status_code, 403)
                client.post("/api/generate", json={"start": {"lat": 51.4857, "lng": -0.6214}, "target_minutes": 30})
                r = client.get("/api/admin/provider-usage", headers={"X-Admin-Token": "founder"})
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertIn("ceilings_per_day", body)
            self.assertIn("starts again on every deploy", body["note"])
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()

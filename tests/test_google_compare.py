"""
The Google comparison harness (backend/tools/google_compare.py). No network:
Google's answer comes from a mock transport, and the key is a dummy.
"""

import asyncio
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import httpx  # noqa: E402

from tools import google_compare as GC  # noqa: E402

REAL_CLIENT = httpx.AsyncClient
CASE = {"id": "synthetic", "start": [52.0, 13.0], "waypoints": [[52.004, 13.0], [52.004, 13.004]],
        "geometry": [[52.0, 13.0], [52.004, 13.0], [52.004, 13.004], [52.0, 13.004], [52.0, 13.0]],
        "minutes_routed": 12.0, "km": 1.8, "built_by": "steered",
        "stops": {"bumps": None, "lights": None, "turn_arounds": 0}}


def encode(points):
    """Google's polyline encoding, for building a fake answer."""
    out, plat, plng = [], 0, 0
    for lat, lng in points:
        for v, prev in ((round(lat * 1e5), plat), (round(lng * 1e5), plng)):
            d = v - prev
            d = ~(d << 1) if d < 0 else d << 1
            while d >= 0x20:
                out.append(chr((0x20 | (d & 0x1F)) + 63))
                d >>= 5
            out.append(chr(d + 63))
        plat, plng = round(lat * 1e5), round(lng * 1e5)
    return "".join(out)


class GeometryTests(unittest.TestCase):
    def test_googles_documented_polyline_decodes(self):
        pts = GC.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
        self.assertEqual(pts, [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)])

    def test_overlap_is_one_on_the_same_line_and_low_on_another_road(self):
        line = [tuple(p) for p in CASE["geometry"]]
        self.assertAlmostEqual(GC.overlap(line, line), 1.0)
        elsewhere = [(p[0] + 0.01, p[1]) for p in line]          # about 1.1 km north
        self.assertLess(GC.overlap(line, elsewhere), 0.05)


class RequestTests(unittest.TestCase):
    def test_the_links_waypoints_go_in_order_as_stopovers(self):
        body = GC.request_body(CASE)
        self.assertEqual([w["location"]["latLng"]["latitude"] for w in body["intermediates"]], [52.004, 52.004])
        self.assertTrue(all(w["via"] is False for w in body["intermediates"]))
        self.assertEqual(body["destination"], body["origin"])     # a loop
        self.assertEqual(body["routingPreference"], "TRAFFIC_AWARE")

    def test_without_the_key_it_stops_and_says_where_it_goes(self):
        with mock.patch.dict(os.environ, {"GOOGLE_ROUTES_API_KEY": ""}), \
                mock.patch("dotenv.load_dotenv", lambda *a, **k: None):
            with self.assertRaises(SystemExit) as caught:
                asyncio.run(GC.run([CASE], 1))
        self.assertIn("backend/.env", str(caught.exception))

    def test_a_run_compares_and_never_writes_the_key(self):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"routes": [{
                "duration": "780s", "distanceMeters": 1900,
                "polyline": {"encodedPolyline": encode([tuple(p) for p in CASE["geometry"]])}}]})

        with mock.patch.dict(os.environ, {"GOOGLE_ROUTES_API_KEY": "dummy-key-123"}), \
                mock.patch("dotenv.load_dotenv", lambda *a, **k: None), \
                mock.patch("httpx.AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler))), \
                mock.patch.object(GC, "stops_on", lambda line, wps: {"bumps": None, "lights": None, "turn_arounds": 0}):
            results = asyncio.run(GC.run([CASE, CASE], limit=1))
        self.assertEqual(len(seen), 1)                              # the limit holds
        self.assertEqual(seen[0].headers["X-Goog-Api-Key"], "dummy-key-123")
        r = results[0]
        self.assertEqual(r["google_minutes"], 13.0)
        self.assertAlmostEqual(r["overlap_ours_on_google"], 1.0, places=2)
        self.assertNotIn("dummy-key-123", json.dumps(results))
        self.assertNotIn("encodedPolyline", json.dumps(results))    # Google's line isn't kept


if __name__ == "__main__":
    unittest.main()

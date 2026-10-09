"""
Address search outside the UK.

Search was pinned to countrySet=GB, so a tester in Berlin got no results for
any address - found while preparing walks for testers there, 9 Oct 2026. With
a position to bias by, the country restriction is now dropped; without one,
the default country still applies.
"""

import asyncio
import os
import sys
import unittest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import httpx  # noqa: E402

from core.models import Coord  # noqa: E402
from core.search import TomTomSearch  # noqa: E402


def _capture():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"results": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return TomTomSearch("test-key", client=client), seen


class SearchRegionTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("SEARCH_DEFAULT_COUNTRIES", None)

    def test_a_position_lifts_the_country_restriction(self):
        search, seen = _capture()
        asyncio.run(search.search("Müggelschlößchenweg 70",
                                  Coord(lat=52.445, lng=13.56), 5))
        self.assertNotIn("countrySet", seen[0])
        self.assertEqual(seen[0]["lat"], "52.445000")

    def test_without_a_position_the_default_country_applies(self):
        search, seen = _capture()
        asyncio.run(search.search("High Street", None, 5))
        self.assertEqual(seen[0]["countrySet"], "GB")

    def test_the_default_country_is_configurable(self):
        os.environ["SEARCH_DEFAULT_COUNTRIES"] = "GB,DE"
        search, seen = _capture()
        asyncio.run(search.search("High Street", None, 5))
        self.assertEqual(seen[0]["countrySet"], "GB,DE")

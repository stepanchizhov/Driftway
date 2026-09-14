"""
Cross-origin access for the deployed shape of the app.

In development the frontend and backend share an origin: vite proxies /api to
localhost:8000, so the browser never sends a preflight and CORS is not
exercised at all. In production they are two separate Render services, so
every non-simple request is preflighted first.

That gap is why allow_methods was wrong for so long without anyone noticing:
DELETE and PUT were absent, and the failure appears in the browser console as
a blocked request with nothing whatsoever in the server logs.

These tests assert the deployed configuration, not the dev one.
"""

import importlib
import os
import sys
import unittest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

FRONTEND_ORIGIN = "https://driftway-front.onrender.com"


def _fresh_app():
    for name in [
        m for m in sys.modules
        if m == "main" or m.startswith("core.") or m.startswith("routes.")
    ]:
        sys.modules.pop(name, None)
    os.environ["ALLOWED_ORIGINS"] = FRONTEND_ORIGIN
    os.environ["ROUTING_PROVIDER"] = "mock"
    main = importlib.import_module("main")
    from fastapi.testclient import TestClient
    return TestClient(main.app)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.client = _fresh_app()

    def tearDown(self):
        self.client.close()
        os.environ.pop("ALLOWED_ORIGINS", None)

    def _preflight(self, method: str, path: str = "/api/account"):
        return self.client.options(path, headers={
            "Origin": FRONTEND_ORIGIN,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "authorization,content-type",
        })

    def test_every_verb_the_frontend_uses_survives_a_preflight(self):
        """GET and POST were always fine. DELETE and PUT were not."""
        for method in ("GET", "POST", "PUT", "DELETE"):
            with self.subTest(method=method):
                res = self._preflight(method)
                self.assertEqual(res.status_code, 200, res.text)
                allowed = res.headers.get("access-control-allow-methods", "")
                self.assertIn(method, allowed)

    def test_the_bearer_token_header_is_permitted(self):
        """Without this, signing in blocks every authenticated request."""
        res = self._preflight("DELETE")
        allowed = res.headers.get("access-control-allow-headers", "").lower()
        self.assertIn("authorization", allowed)

    def test_the_frontend_origin_is_echoed_back(self):
        res = self._preflight("POST")
        self.assertEqual(
            res.headers.get("access-control-allow-origin"), FRONTEND_ORIGIN)

    def test_an_unlisted_origin_is_not_granted_access(self):
        res = self.client.options("/api/account", headers={
            "Origin": "https://not-driftway.example",
            "Access-Control-Request-Method": "DELETE",
        })
        self.assertNotEqual(
            res.headers.get("access-control-allow-origin"),
            "https://not-driftway.example",
        )

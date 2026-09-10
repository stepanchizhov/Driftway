"""
The API must survive a database it cannot reach.

Bible section 4: "The core - loops and detours from the current location -
must work with zero stored travel data. Only convenience features may require
storage." A crash-looping service breaks that promise to protect favourites,
which nobody is using at the moment their baby is asleep in the car.

This is a regression test for a real production incident: Render's free
Postgres instance stopped resolving, init_db() raised at import time, uvicorn
could not load the app, and the whole API crash-looped - taking routing and
search down with it.
"""

import importlib
import os
import sys
import unittest


class StorageOutageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        backend = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend")
        if backend not in sys.path:
            sys.path.insert(0, backend)

        # A URL that builds fine but cannot be connected to.
        cls._prev = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = "sqlite:////nonexistent-dir/nope.db"
        for mod in ("core.db", "routes.api", "main"):
            sys.modules.pop(mod, None)
        cls.db = importlib.import_module("core.db")
        cls.main = importlib.import_module("main")

    @classmethod
    def tearDownClass(cls):
        if cls._prev is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = cls._prev
        for mod in ("core.db", "routes.api", "main"):
            sys.modules.pop(mod, None)

    def test_the_app_still_imports_when_storage_is_unreachable(self):
        """The crash loop: uvicorn could not even load the module."""
        self.assertTrue(hasattr(self.main, "app"))

    def test_storage_reports_itself_unavailable(self):
        self.assertFalse(self.db.storage_available())

    def test_health_names_which_part_is_down(self):
        from fastapi.testclient import TestClient

        body = TestClient(self.main.app).get("/api/health").json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["storage"], "unavailable")

    def test_saving_features_answer_503_not_500(self):
        """503 says 'this dependency is down', which the client can act on.
        A 500 just looks like a bug."""
        from fastapi.testclient import TestClient

        client = TestClient(self.main.app)
        for response in (
            client.get("/api/favourites?owner=someone"),
            client.post("/api/feedback",
                        json={"route_id": "x", "predicted_minutes": 30.0}),
        ):
            self.assertEqual(response.status_code, 503)
            self.assertIn("Routes still work", response.json()["detail"])

    def test_route_generation_is_unaffected(self):
        """The whole point: the core keeps working."""
        from fastapi.testclient import TestClient

        response = TestClient(self.main.app).post(
            "/api/generate",
            json={"start": {"lat": 51.4857, "lng": -0.6214},
                  "target_minutes": 30, "tolerance_minutes": 10,
                  "road_profile": "mixed", "direction": "surprise"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["routes"])


if __name__ == "__main__":
    unittest.main()

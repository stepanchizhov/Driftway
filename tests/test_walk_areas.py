"""
Curated walks beyond the founder's area (core/walking/areas.py): a parent's
request keeps only a grid square; the job builds and uploads walks; AI text is
shown only after the founder approves it. No network: Overpass is mocked.
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import httpx  # noqa: E402

from test_identity_auth0 import ADMIN, _fresh  # noqa: E402

JOB = "test-walks-job-token"
WALKS_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "data", "walks")
TRAILS = {"elements": [
    {"type": "relation", "id": 1, "tags": {"name": "Long Trail", "distance": "25", "roundtrip": "no"}},
    {"type": "relation", "id": 2, "tags": {"name": "Pond Loop", "distance": "2.1", "roundtrip": "yes",
                                           "operator": "Parks Dept", "website": "https://example.org/pond"}},
    {"type": "relation", "id": 3, "tags": {"distance": "3"}},                      # no name
]}


def overpass(seen=None, status=200):
    def handler(request):
        if seen is not None:
            seen.append(request.read().decode())
        return httpx.Response(status, json=TRAILS) if status == 200 else httpx.Response(status, text="busy")
    real = httpx.AsyncClient
    return mock.patch("routes.walk_areas.httpx.AsyncClient",
                      lambda **kw: real(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "transport"}))


def a_walk(walk_id="osm-pond-loop"):
    with open(os.path.join(WALKS_DIR, "osm-views-route-runnymede.json"), encoding="utf-8") as f:
        route = json.load(f)
    route.update({"id": walk_id, "name": "Pond Loop", "area": "Somewhere"})
    # A different trail from the file walk it was copied from.
    route["sources"] = [s for s in route["sources"] if s["id"] != "osm-route"]
    return route


class _Base(unittest.TestCase):
    def setUp(self):
        os.environ["WALKING_ENABLED"] = "true"
        os.environ["WALKS_JOB_TOKEN"] = JOB
        self.client, _ = _fresh(configured=False)
        from core.walking import areas
        areas.forget_cache()

    def tearDown(self):
        self.client.close()
        for k in ("WALKING_ENABLED", "WALKS_JOB_TOKEN"):
            os.environ.pop(k, None)

    def ask(self, lat=52.5161, lng=13.3777, seen=None, status=200):
        with overpass(seen, status):
            return self.client.post("/api/walks/areas", json={"lat": lat, "lng": lng})

    def job(self):
        return {"X-Walks-Job-Token": JOB}


class AskTests(_Base):
    def test_a_request_lists_mapped_trails_at_once_and_queues_the_square(self):
        r = self.ask()
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["status"], "queued")
        self.assertEqual([t["name"] for t in body["trails"]], ["Pond Loop", "Long Trail"])
        self.assertEqual(body["trails"][0]["website"], "https://example.org/pond")

    def test_only_the_square_is_kept_never_the_position(self):
        seen = []
        self.ask(52.516123, 13.377712, seen=seen)
        from core.db import SessionLocal
        from core.walking.areas import WalkArea
        s = SessionLocal()
        rows = s.query(WalkArea).all()
        s.close()
        self.assertEqual([a.cell for a in rows], ["525:133"])
        stored = json.dumps([{c.name: str(getattr(a, c.name)) for c in WalkArea.__table__.columns} for a in rows])
        self.assertNotIn("52.516", stored)
        self.assertNotIn("13.377", stored)
        # Overpass is asked about the square's edges, not the position.
        self.assertIn("52.5", seen[0])
        self.assertNotIn("52.516", seen[0])

    def test_the_trail_list_is_looked_up_once_per_square(self):
        seen = []
        self.ask(seen=seen)
        self.ask(52.52, 13.39, seen=seen)        # same square
        self.assertEqual(len(seen), 1)

    def test_a_busy_map_service_still_queues_the_square(self):
        r = self.ask(status=504)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "queued")
        self.assertIsNone(r.json()["trails"])


class JobTests(_Base):
    def test_the_job_sees_the_queue_and_uploads_a_walk_that_then_shows(self):
        self.ask()
        q = self.client.get("/api/admin/walk-areas", headers=self.job()).json()
        self.assertEqual(q[0]["cell"], "525:133")
        r = self.client.put("/api/admin/curated-walks/osm-pond-loop", headers=self.job(),
                            json={"cell": "525:133", "source": "osm_relation:2", "route": a_walk()})
        self.assertEqual(r.status_code, 200, r.text)
        self.client.post("/api/admin/walk-areas/525:133", headers=self.job(),
                         json={"status": "ready", "note": "1 built"})
        names = [w["name"] for w in self.client.post("/api/walks/assess", json={"profile": "walker"}).json()["walks"]]
        self.assertIn("Pond Loop", names)

    def test_without_the_token_nothing(self):
        for call in (lambda h: self.client.get("/api/admin/walk-areas", headers=h),
                     lambda h: self.client.put("/api/admin/curated-walks/x", headers=h,
                                               json={"cell": "1:1", "route": {}})):
            self.assertEqual(call({}).status_code, 403)
            self.assertEqual(call({"X-Walks-Job-Token": "wrong"}).status_code, 403)

    def test_a_malformed_walk_is_refused(self):
        r = self.client.put("/api/admin/curated-walks/osm-x", headers=self.job(),
                            json={"cell": "525:133", "route": {"id": "osm-x", "name": "x"}})
        self.assertEqual(r.status_code, 422)


class DescriptionTests(_Base):
    TEXT = "A short circular walk round the pond on firm paths, with one kissing gate near the start."

    def setUp(self):
        super().setUp()
        self.client.put("/api/admin/curated-walks/osm-pond-loop", headers=self.job(),
                        json={"cell": "525:133", "route": a_walk()})
        r = self.client.post("/api/admin/curated-walks/osm-pond-loop/description", headers=self.job(),
                             json={"text": self.TEXT, "model": "test-model"})
        self.assertEqual(r.status_code, 200, r.text)

    def shown(self):
        from core.walking import areas
        areas.forget_cache()
        walks = self.client.post("/api/walks/assess", json={"profile": "walker"}).json()["walks"]
        return next(w for w in walks if w["id"] == "osm-pond-loop")["description"]

    def test_ai_text_is_not_shown_until_the_founder_approves_it(self):
        self.assertIsNone(self.shown())
        r = self.client.post("/api/admin/curated-walks/osm-pond-loop/description/review",
                             headers={"X-Admin-Token": ADMIN}, json={"decision": "approve"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.shown(), self.TEXT)

    def test_the_job_cannot_approve(self):
        r = self.client.post("/api/admin/curated-walks/osm-pond-loop/description/review",
                             headers=self.job(), json={"decision": "approve"})
        self.assertEqual(r.status_code, 403)

    def test_the_founder_can_correct_while_approving_or_reject(self):
        fixed = "A short circular walk round the pond. One kissing gate near the start."
        self.client.post("/api/admin/curated-walks/osm-pond-loop/description/review",
                         headers={"X-Admin-Token": ADMIN}, json={"decision": "approve", "text": fixed})
        self.assertEqual(self.shown(), fixed)
        self.client.post("/api/admin/curated-walks/osm-pond-loop/description/review",
                         headers={"X-Admin-Token": ADMIN}, json={"decision": "reject"})
        self.assertIsNone(self.shown())

    def test_markup_is_refused(self):
        r = self.client.post("/api/admin/curated-walks/osm-pond-loop/description", headers=self.job(),
                             json={"text": "<script>alert(1)</script> and more words here", "model": "m"})
        self.assertEqual(r.status_code, 422)

    def test_a_new_description_goes_back_to_pending(self):
        self.client.post("/api/admin/curated-walks/osm-pond-loop/description/review",
                         headers={"X-Admin-Token": ADMIN}, json={"decision": "approve"})
        self.client.post("/api/admin/curated-walks/osm-pond-loop/description", headers=self.job(),
                         json={"text": "A different description written later by the job.", "model": "m"})
        self.assertIsNone(self.shown())


class SameTrailTests(_Base):
    def test_a_trail_already_curated_by_hand_is_not_shown_twice(self):
        # The job builds the Runnymede Views Route under its own id; the file
        # walk osm-views-route-runnymede is the same mapped trail.
        route = a_walk("osm-19761171-views-route-runnymede")
        route["name"] = "Views Route (job)"
        route["sources"].append({"id": "osm-route", "label": "OpenStreetMap route relation 19761171"})
        self.client.put("/api/admin/curated-walks/osm-19761171-views-route-runnymede",
                        headers=self.job(), json={"cell": "514:-6", "route": route})
        names = [w["name"] for w in self.client.post("/api/walks/assess", json={"profile": "walker"}).json()["walks"]]
        self.assertIn("Views Route", names)
        self.assertNotIn("Views Route (job)", names)


class FileWinsTests(_Base):
    def test_a_stored_walk_never_replaces_one_curated_by_hand(self):
        route = a_walk("windsor-long-walk")
        route["name"] = "Impostor"
        self.client.put("/api/admin/curated-walks/windsor-long-walk", headers=self.job(),
                        json={"cell": "514:-7", "route": route})
        walks = self.client.post("/api/walks/assess", json={"profile": "walker"}).json()["walks"]
        self.assertNotIn("Impostor", [w["name"] for w in walks])




class SuitabilityWordingTests(unittest.TestCase):
    """15 Oct 2026: an approved description is wording, not a check of gates,
    surfaces or access, so it may not claim suitability."""

    def test_a_suitability_claim_is_refused(self):
        from tools.walk_area_job import check
        facts = {"length_km": 3.2}
        ok = "A 3.2 km loop along the river and through a wood, returning past the church."
        self.assertIsNone(check(ok, facts))
        for word in ("easy", "safe", "pram-friendly", "step-free", "suitable", "no stiles"):
            text = f"A 3.2 km loop along the river, {word} for most, returning past the church."
            self.assertIsNotNone(check(text, facts), word)


if __name__ == "__main__":
    unittest.main()

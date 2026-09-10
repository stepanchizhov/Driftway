"""
Meet Halfway, Milestone 5: settling on a venue.

Who gets to decide is a permission question, and the wrong answer here is one
parent overriding the other. For staging the organiser decides after the votes,
which is a product choice recorded in the endpoint docstring - not a technical
constraint.
"""

import importlib
import os
import sys
import tempfile
import unittest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

ORIGIN_A = {"lat": 51.4857, "lng": -0.6214}
ORIGIN_B = {"lat": 51.5216, "lng": -0.7205}
VENUE = {"lat": 51.50, "lng": -0.67}


def _reset_modules() -> None:
    """Drop every application module so the next import rebuilds them all.

    This has to be all-or-nothing. Reloading `core.router` while leaving
    `core.generator` cached leaves two copies of `EvaluatedRoute` in memory,
    and the `isinstance` check inside the generator then rejects perfectly good
    routes built by the fresh router - which shows up as an unrelated
    assertion failing, only when tests run together.
    """
    for name in [
        m for m in sys.modules
        if m == "main" or m.startswith("core.") or m.startswith("routes.")
    ]:
        sys.modules.pop(name, None)


def _fresh_app():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp.name.replace(os.sep, '/')}"
    os.environ["MEET_HALFWAY_ENABLED"] = "true"
    os.environ["ROUTING_PROVIDER"] = "mock"
    os.environ["ADMIN_API_TOKEN"] = "test-admin"
    _reset_modules()
    main = importlib.import_module("main")
    from fastapi.testclient import TestClient
    return TestClient(main.app)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.client = _fresh_app()
        made = self.client.post("/api/meetups", json={
            "mode": "explore", "categories": [],
            "organiser": {"start": ORIGIN_A, "display_name": "A"},
        }).json()
        self.mid = made["meetup_id"]
        self.a = made["your_join_token"]
        self.b = made["participant_invite_token"]
        self.slug = made["results_slug"]
        self.client.post(f"/api/meetups/{self.mid}/participants/{self.b}",
                         json={"start": ORIGIN_B, "display_name": "B"})
        view = self.client.post(f"/api/meetups/{self.mid}/venues/{self.a}",
                                json={"name": "The Park", "coord": VENUE}).json()
        self.venue_id = view["candidates"][0]["id"]

    def tearDown(self):
        self.client.close()

    def _select(self, token):
        return self.client.post(
            f"/api/meetups/{self.mid}/selection/{token}",
            params={"candidate_id": self.venue_id},
        )

    def test_the_organiser_can_settle_on_a_venue(self):
        r = self._select(self.a)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["selected_venue_id"], self.venue_id)
        self.assertEqual(body["status"], "decided")

    def test_a_guest_cannot_settle_on_a_venue(self):
        r = self._select(self.b)
        self.assertEqual(r.status_code, 403)
        self.assertIn("set up the meetup", r.json()["detail"])

    def test_the_choice_is_visible_to_everyone(self):
        self._select(self.a)
        guest = self.client.get(f"/api/meetups/{self.mid}/{self.b}").json()
        self.assertEqual(guest["selected_venue_id"], self.venue_id)
        public = self.client.get(f"/api/meetups/results/{self.slug}").json()
        self.assertEqual(public["selected_venue_id"], self.venue_id)

    def test_the_organiser_can_change_their_mind(self):
        self._select(self.a)
        r = self.client.delete(f"/api/meetups/{self.mid}/selection/{self.a}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(r.json()["selected_venue_id"])
        self.assertEqual(r.json()["status"], "ready")

    def test_a_guest_cannot_undo_the_choice(self):
        self._select(self.a)
        r = self.client.delete(f"/api/meetups/{self.mid}/selection/{self.b}")
        self.assertEqual(r.status_code, 403)

    def test_a_venue_from_another_meetup_cannot_be_selected(self):
        other = self.client.post("/api/meetups", json={
            "mode": "explore", "categories": [],
            "organiser": {"start": ORIGIN_A},
        }).json()
        elsewhere = self.client.post(
            f"/api/meetups/{other['meetup_id']}/venues/{other['your_join_token']}",
            json={"name": "Somewhere Else", "coord": VENUE},
        ).json()["candidates"][0]["id"]

        r = self.client.post(
            f"/api/meetups/{self.mid}/selection/{self.a}",
            params={"candidate_id": elsewhere},
        )
        self.assertEqual(r.status_code, 404)

    def test_the_results_link_cannot_settle_a_venue(self):
        r = self.client.post(
            f"/api/meetups/{self.mid}/selection/{self.slug}",
            params={"candidate_id": self.venue_id},
        )
        self.assertEqual(r.status_code, 404)


class DelayedArrivalHandoffTests(unittest.TestCase):
    """The chosen venue feeds the existing destination routing, not a copy of it."""

    def setUp(self):
        self.client = _fresh_app()

    def tearDown(self):
        self.client.close()

    def test_a_venue_can_be_driven_to_over_a_chosen_total_time(self):
        r = self.client.post("/api/generate", json={
            "start": ORIGIN_A,
            "finish": VENUE,
            "target_minutes": 45,
            "tolerance_minutes": 10,
            "road_profile": "mixed",
            "direction": "surprise",
            "mode": "destination",
        })
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["mode"], "destination")
        self.assertIsNotNone(body["direct_minutes"])
        self.assertTrue(body["routes"])
        # Total journey semantics, inherited rather than reimplemented.
        self.assertLessEqual(abs(body["routes"][0]["predicted_minutes"] - 45), 12)

    def test_asking_for_less_than_the_direct_drive_returns_the_direct_route(self):
        """The floor applies here exactly as it does in the planner."""
        r = self.client.post("/api/generate", json={
            "start": ORIGIN_A, "finish": VENUE, "target_minutes": 5,
            "tolerance_minutes": 10, "road_profile": "mixed",
            "direction": "surprise", "mode": "destination",
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["routes"][0]["is_direct"])
        self.assertIsNotNone(body["notice"])

    def test_group_travel_times_are_not_recalculated_from_a_padded_route(self):
        """One parent padding their own drive must not change what the group
        sees: those numbers describe the direct journey for everyone."""
        made = self.client.post("/api/meetups", json={
            "mode": "explore", "categories": [],
            "organiser": {"start": ORIGIN_A, "display_name": "A"},
        }).json()
        mid, a, b = (made["meetup_id"], made["your_join_token"],
                     made["participant_invite_token"])
        self.client.post(f"/api/meetups/{mid}/participants/{b}",
                         json={"start": ORIGIN_B, "display_name": "B"})
        self.client.post(f"/api/meetups/{mid}/venues/{a}",
                         json={"name": "The Park", "coord": VENUE})
        before = self.client.post(f"/api/meetups/{mid}/candidates/{a}").json()
        times_before = [t["direct_minutes"]
                        for t in before["candidates"][0]["participant_travel"]]

        # One parent pads their own journey.
        self.client.post("/api/generate", json={
            "start": ORIGIN_A, "finish": VENUE, "target_minutes": 60,
            "tolerance_minutes": 10, "road_profile": "mixed",
            "direction": "surprise", "mode": "destination",
        })

        after = self.client.get(f"/api/meetups/{mid}/{a}").json()
        times_after = [t["direct_minutes"]
                       for t in after["candidates"][0]["participant_travel"]]
        self.assertEqual(times_before, times_after)


if __name__ == "__main__":
    unittest.main()

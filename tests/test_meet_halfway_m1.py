"""
Meet Halfway, Milestone 1: identity, capabilities, privacy, storage isolation.

The tests that matter most here are the negative ones. A meetup feature is a
place where one family's home address can leak to another family, so most of
this file is about what must *not* appear in a payload.
"""

import importlib
import os
import sys
import tempfile
import unittest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

ADMIN_TOKEN = "test-admin-token"

# Two Windsor-area origins, far enough apart to be distinguishable.
ORIGIN_A = {"lat": 51.4857, "lng": -0.6214}
ORIGIN_B = {"lat": 51.5216, "lng": -0.7205}


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


def _fresh_app(**env):
    """Import the app against a throwaway SQLite file and a chosen env."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp.name.replace(os.sep, '/')}"
    os.environ["MEET_HALFWAY_ENABLED"] = env.get("MEET_HALFWAY_ENABLED", "true")
    os.environ["REGISTRATION_MODE"] = env.get("REGISTRATION_MODE", "invite_only")
    os.environ["ADMIN_API_TOKEN"] = env.get("ADMIN_API_TOKEN", ADMIN_TOKEN)
    os.environ["ROUTING_PROVIDER"] = "mock"
    _reset_modules()
    main = importlib.import_module("main")
    from fastapi.testclient import TestClient
    return TestClient(main.app), tmp.name


class MeetHalfwayTestCase(unittest.TestCase):
    def setUp(self):
        self.client, self._db = _fresh_app()

    def tearDown(self):
        self.client.close()

    # -- helpers -----------------------------------------------------------

    def _mint_invite(self):
        r = self.client.post(
            "/api/admin/beta-invites", headers={"X-Admin-Token": ADMIN_TOKEN}
        )
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _make_meetup(self, hide=True):
        r = self.client.post("/api/meetups", json={
            "mode": "explore",
            "categories": [],
            "organiser": {
                "start": ORIGIN_A,
                "hide_exact_origin": hide,
                "display_name": "Organiser",
                "preferred_minutes": 30,
                "max_minutes": 50,
            },
        })
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()


# ------------------------------------------------------ registration gate

class RegistrationGateTests(MeetHalfwayTestCase):
    def test_invite_only_rejects_account_creation_without_an_invite(self):
        r = self.client.post("/api/auth/accept-beta-invite",
                             json={"invite_token": ""})
        # 422 since the token moved into a validated body: an empty token is
        # now refused by schema validation before any invite lookup happens.
        # Either way it is refused, which is what this test is about.
        self.assertIn(r.status_code, (400, 422))

    def test_a_bogus_invite_token_is_rejected(self):
        r = self.client.post("/api/auth/accept-beta-invite",
                             json={"invite_token": "not-a-real-token"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("not valid", r.json()["detail"])

    def test_a_valid_invite_creates_exactly_one_account(self):
        invite = self._mint_invite()
        r = self.client.post("/api/auth/accept-beta-invite", json={
            "invite_token": invite["invite_token"], "display_name": "Stepan",
        })
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["display_name"], "Stepan")

        # Second use of the same invite must fail.
        again = self.client.post("/api/auth/accept-beta-invite",
                                 json={"invite_token": invite["invite_token"]})
        self.assertEqual(again.status_code, 400)
        self.assertIn("already been used", again.json()["detail"])

    def test_a_revoked_invite_is_rejected(self):
        invite = self._mint_invite()
        rv = self.client.post(
            f"/api/admin/beta-invites/{invite['id']}/revoke",
            headers={"X-Admin-Token": ADMIN_TOKEN},
        )
        self.assertEqual(rv.status_code, 200)
        r = self.client.post("/api/auth/accept-beta-invite",
                             json={"invite_token": invite["invite_token"]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("revoked", r.json()["detail"])

    def test_closed_mode_refuses_even_a_valid_invite(self):
        """The gate is server-side, so a good token is still useless when the
        door is shut."""
        invite = self._mint_invite()
        client, _ = _fresh_app(REGISTRATION_MODE="closed")
        r = client.post("/api/auth/accept-beta-invite",
                        json={"invite_token": invite["invite_token"]})
        self.assertEqual(r.status_code, 403)
        client.close()

    def test_an_unrecognised_registration_mode_does_not_fall_open(self):
        from core.config import RegistrationMode, registration_mode
        os.environ["REGISTRATION_MODE"] = "opne"  # typo
        self.assertEqual(registration_mode(), RegistrationMode.INVITE_ONLY)
        os.environ["REGISTRATION_MODE"] = "invite_only"

    def test_there_is_no_public_signup_endpoint(self):
        for path in ("/api/auth/register", "/api/auth/signup", "/api/register"):
            self.assertEqual(self.client.post(path, json={}).status_code, 404)


class AdminGuardTests(MeetHalfwayTestCase):
    def test_minting_an_invite_requires_the_admin_token(self):
        self.assertEqual(self.client.post("/api/admin/beta-invites").status_code, 403)
        self.assertEqual(
            self.client.post("/api/admin/beta-invites",
                             headers={"X-Admin-Token": "wrong"}).status_code, 403)

    def test_unconfigured_admin_access_refuses_rather_than_defaults_open(self):
        client, _ = _fresh_app(ADMIN_API_TOKEN="")
        r = client.post("/api/admin/beta-invites")
        self.assertEqual(r.status_code, 503)
        client.close()

    def test_listing_invites_never_returns_raw_tokens(self):
        created = self._mint_invite()
        r = self.client.get("/api/admin/beta-invites",
                            headers={"X-Admin-Token": ADMIN_TOKEN})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body)
        for row in body:
            self.assertIsNone(row["invite_token"])
        self.assertNotIn(created["invite_token"], r.text)


# ------------------------------------------------------------ capabilities

class CapabilitySeparationTests(MeetHalfwayTestCase):
    def test_the_three_capabilities_are_not_interchangeable(self):
        invite = self._mint_invite()
        meetup = self._make_meetup()

        # A beta invite is not a join token.
        r = self.client.get(
            f"/api/meetups/{meetup['meetup_id']}/{invite['invite_token']}")
        self.assertEqual(r.status_code, 404)

        # A results slug is not a join token.
        r = self.client.get(
            f"/api/meetups/{meetup['meetup_id']}/{meetup['results_slug']}")
        self.assertEqual(r.status_code, 404)

        # A join token is not a results slug.
        r = self.client.get(
            f"/api/meetups/results/{meetup['your_join_token']}")
        self.assertEqual(r.status_code, 404)

        # A join token is not an admin token.
        r = self.client.post(
            "/api/admin/beta-invites",
            headers={"X-Admin-Token": meetup["your_join_token"]})
        self.assertEqual(r.status_code, 403)

    def test_the_organiser_gets_a_separate_token_from_the_invitee(self):
        meetup = self._make_meetup()
        self.assertNotEqual(meetup["your_join_token"],
                            meetup["participant_invite_token"])

    def test_a_join_token_from_one_meetup_does_not_work_on_another(self):
        first = self._make_meetup()
        second = self._make_meetup()
        r = self.client.get(
            f"/api/meetups/{second['meetup_id']}/{first['your_join_token']}")
        self.assertEqual(r.status_code, 404)

    def test_the_public_results_link_cannot_write(self):
        meetup = self._make_meetup()
        r = self.client.post(
            f"/api/meetups/{meetup['meetup_id']}/participants/{meetup['results_slug']}",
            json={"start": ORIGIN_B, "hide_exact_origin": True},
        )
        self.assertEqual(r.status_code, 404)


# ----------------------------------------------------------------- privacy

class OriginPrivacyTests(MeetHalfwayTestCase):
    def _two_party_meetup(self, guest_hides=True):
        meetup = self._make_meetup(hide=True)
        r = self.client.post(
            f"/api/meetups/{meetup['meetup_id']}/participants/"
            f"{meetup['participant_invite_token']}",
            json={"start": ORIGIN_B, "hide_exact_origin": guest_hides,
                  "display_name": "Guest"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        return meetup

    def test_a_hidden_exact_origin_never_appears_in_public_results(self):
        meetup = self._two_party_meetup()
        r = self.client.get(f"/api/meetups/results/{meetup['results_slug']}")
        self.assertEqual(r.status_code, 200)
        raw = r.text

        # The full-precision coordinates must not be recoverable anywhere.
        for value in (ORIGIN_A["lat"], ORIGIN_A["lng"],
                      ORIGIN_B["lat"], ORIGIN_B["lng"]):
            self.assertNotIn(str(value), raw,
                             f"exact coordinate {value} leaked into public results")

        for p in r.json()["participants"]:
            self.assertEqual(p["origin_precision"], "approximate")

    def test_no_join_token_appears_in_public_results(self):
        meetup = self._two_party_meetup()
        raw = self.client.get(f"/api/meetups/results/{meetup['results_slug']}").text
        self.assertNotIn(meetup["your_join_token"], raw)
        self.assertNotIn(meetup["participant_invite_token"], raw)

    def test_a_participant_sees_their_own_exact_origin_but_not_a_peers(self):
        meetup = self._two_party_meetup()
        r = self.client.get(
            f"/api/meetups/{meetup['meetup_id']}/{meetup['your_join_token']}")
        self.assertEqual(r.status_code, 200)
        body = r.json()

        me = [p for p in body["participants"] if p["is_you"]]
        them = [p for p in body["participants"] if not p["is_you"]]
        self.assertEqual(len(me), 1)
        self.assertEqual(me[0]["origin_precision"], "exact")
        self.assertAlmostEqual(me[0]["display_coord"]["lat"], ORIGIN_A["lat"], places=6)

        for other in them:
            self.assertEqual(other["origin_precision"], "approximate")
            self.assertNotAlmostEqual(
                other["display_coord"]["lat"], ORIGIN_B["lat"], places=4,
                msg="a peer's exact origin was returned",
            )

    def test_hiding_defaults_to_on(self):
        meetup = self._make_meetup()
        r = self.client.post(
            f"/api/meetups/{meetup['meetup_id']}/participants/"
            f"{meetup['participant_invite_token']}",
            json={"start": ORIGIN_B},  # hide_exact_origin omitted entirely
        )
        self.assertEqual(r.status_code, 200)
        guest = [p for p in r.json()["participants"] if p["is_you"]][0]
        # The guest sees their own exactly; the public view is what proves the
        # default took effect.
        pub = self.client.get(f"/api/meetups/results/{meetup['results_slug']}").json()
        self.assertTrue(
            all(p["origin_precision"] == "approximate" for p in pub["participants"]))
        self.assertEqual(guest["is_you"], True)

    def test_a_parent_who_opts_in_is_shown_exactly(self):
        """Hiding is the default, not a rule - sharing must still be possible."""
        meetup = self._two_party_meetup(guest_hides=False)
        pub = self.client.get(f"/api/meetups/results/{meetup['results_slug']}").json()
        precisions = {p["origin_precision"] for p in pub["participants"]}
        self.assertIn("exact", precisions)
        self.assertIn("approximate", precisions)

    def test_coarsening_is_deterministic(self):
        """Re-rolled jitter leaks the true point to anyone who samples and
        averages; a fixed grid does not."""
        from core.meetups import coarsen
        first = coarsen(51.48571, -0.62143)
        for _ in range(5):
            self.assertEqual(coarsen(51.48571, -0.62143), first)
        # And it genuinely moves the point off the original.
        self.assertNotEqual(first, (51.48571, -0.62143))


class GuestParticipationTests(MeetHalfwayTestCase):
    def test_a_guest_can_join_without_an_account(self):
        meetup = self._make_meetup()
        r = self.client.post(
            f"/api/meetups/{meetup['meetup_id']}/participants/"
            f"{meetup['participant_invite_token']}",
            json={"start": ORIGIN_B, "display_name": "Guest"},
        )
        self.assertEqual(r.status_code, 200, r.text)

    def test_guests_can_still_join_while_registration_is_closed(self):
        """Closing account creation must not close the collaboration funnel."""
        client, _ = _fresh_app(REGISTRATION_MODE="closed")
        made = client.post("/api/meetups", json={
            "mode": "explore", "categories": [],
            "organiser": {"start": ORIGIN_A},
        }).json()
        r = client.post(
            f"/api/meetups/{made['meetup_id']}/participants/"
            f"{made['participant_invite_token']}",
            json={"start": ORIGIN_B},
        )
        self.assertEqual(r.status_code, 200, r.text)
        client.close()

    def test_an_account_email_never_reaches_a_meetup_payload(self):
        invite = self._mint_invite()
        self.client.post("/api/auth/accept-beta-invite", json={
            "invite_token": invite["invite_token"],
            "email": "founder@example.com",
            "display_name": "Founder",
        })
        meetup = self._make_meetup()
        self.client.post(
            f"/api/meetups/{meetup['meetup_id']}/participants/"
            f"{meetup['participant_invite_token']}",
            json={"start": ORIGIN_B},
        )
        for path in (
            f"/api/meetups/results/{meetup['results_slug']}",
            f"/api/meetups/{meetup['meetup_id']}/{meetup['your_join_token']}",
        ):
            self.assertNotIn("founder@example.com", self.client.get(path).text)

    def test_the_signed_in_account_view_omits_the_email(self):
        invite = self._mint_invite()
        self.client.post("/api/auth/accept-beta-invite", json={
            "invite_token": invite["invite_token"],
            "email": "founder@example.com",
        })
        body = self.client.get("/api/auth/me").json()
        self.assertIsNotNone(body)
        self.assertNotIn("email", body)


# -------------------------------------------------------------- feature flag

class FeatureFlagTests(unittest.TestCase):
    def test_the_whole_surface_is_absent_when_the_flag_is_off(self):
        client, _ = _fresh_app(MEET_HALFWAY_ENABLED="false")
        r = client.post("/api/meetups", json={
            "mode": "explore", "categories": [],
            "organiser": {"start": ORIGIN_A},
        })
        self.assertEqual(r.status_code, 404)
        client.close()

    def test_routing_is_unaffected_by_the_meetup_flag(self):
        client, _ = _fresh_app(MEET_HALFWAY_ENABLED="false")
        r = client.post("/api/generate", json={
            "start": ORIGIN_A, "target_minutes": 30, "tolerance_minutes": 10,
            "road_profile": "mixed", "direction": "surprise",
        })
        self.assertEqual(r.status_code, 200)
        client.close()


# --------------------------------------------------------- storage isolation

class MeetupStorageIsolationTests(unittest.TestCase):
    """The incident this repository already suffered, in its meetup form."""

    @classmethod
    def setUpClass(cls):
        os.environ["DATABASE_URL"] = "sqlite:////nonexistent-dir/nope.db"
        os.environ["MEET_HALFWAY_ENABLED"] = "true"
        os.environ["ROUTING_PROVIDER"] = "mock"
        _reset_modules()
        cls.main = importlib.import_module("main")
        from fastapi.testclient import TestClient
        cls.client = TestClient(cls.main.app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        os.environ.pop("DATABASE_URL", None)
        _reset_modules()

    def test_the_app_still_imports_without_meetup_storage(self):
        self.assertTrue(hasattr(self.main, "app"))

    def test_meetup_endpoints_return_a_named_503(self):
        r = self.client.post("/api/meetups", json={
            "mode": "explore", "categories": [],
            "organiser": {"start": ORIGIN_A},
        })
        self.assertEqual(r.status_code, 503)
        self.assertIn("meetup_storage_unavailable", r.json()["detail"])

    def test_route_generation_still_works(self):
        r = self.client.post("/api/generate", json={
            "start": ORIGIN_A, "target_minutes": 30, "tolerance_minutes": 10,
            "road_profile": "mixed", "direction": "surprise",
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["routes"])

    def test_search_still_works(self):
        r = self.client.get("/api/search", params={"q": "windsor"})
        self.assertEqual(r.status_code, 200)

    def test_health_reports_the_outage(self):
        body = self.client.get("/api/health").json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["storage"], "unavailable")


if __name__ == "__main__":
    unittest.main()

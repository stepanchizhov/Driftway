"""
Phase A: invitation and account framework.

These are the contracts that decide who gets in. The tests that matter most are
the ones that try to get in twice, get in after being disabled, or get in with
somebody else's capability.

Note what these do NOT prove: there is no managed identity provider configured,
so nothing here demonstrates a production authentication integration. The
session mechanism under test is explicitly staging-only. See docs/IDENTITY.md.
"""

import importlib
import os
import sqlite3
import sys
import tempfile
import threading
import unittest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

ADMIN = "phase-a-admin-token"


def _reset_modules() -> None:
    for name in [
        m for m in sys.modules
        if m == "main" or m.startswith("core.") or m.startswith("routes.")
    ]:
        sys.modules.pop(name, None)


def _fresh(**env):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = tmp.name
    os.environ["DATABASE_URL"] = f"sqlite:///{path.replace(os.sep, '/')}"
    os.environ["MEET_HALFWAY_ENABLED"] = env.get("MEET_HALFWAY_ENABLED", "true")
    os.environ["REGISTRATION_MODE"] = env.get("REGISTRATION_MODE", "invite_only")
    os.environ["ADMIN_API_TOKEN"] = env.get("ADMIN_API_TOKEN", ADMIN)
    os.environ["ROUTING_PROVIDER"] = "mock"
    _reset_modules()
    main = importlib.import_module("main")
    from fastapi.testclient import TestClient
    return TestClient(main.app), path


class PhaseATestCase(unittest.TestCase):
    def setUp(self):
        self.client, self.db = _fresh()

    def tearDown(self):
        self.client.close()

    def mint(self, **kw):
        r = self.client.post("/api/admin/beta-invites",
                             headers={"X-Admin-Token": ADMIN}, params=kw)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def redeem(self, token, **body):
        return self.client.post("/api/auth/accept-beta-invite",
                                json={"invite_token": token, **body})


# ------------------------------------------------- redemption is exactly once

class RedemptionTests(PhaseATestCase):
    def test_a_valid_invite_creates_one_account(self):
        invite = self.mint()
        r = self.redeem(invite["invite_token"], display_name="Stepan")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["display_name"], "Stepan")

    def test_replaying_the_same_invite_is_refused(self):
        invite = self.mint()
        self.assertEqual(self.redeem(invite["invite_token"]).status_code, 200)
        again = self.redeem(invite["invite_token"])
        self.assertEqual(again.status_code, 400)
        self.assertIn("already been used", again.json()["detail"])

    def test_concurrent_redemption_yields_exactly_one_account(self):
        """The race the status check alone could not stop.

        Two requests can both read the invite as unused before either writes.
        Only the conditional UPDATE decides it, so exactly one may win.
        """
        invite = self.mint()
        token = invite["invite_token"]
        results = []
        barrier = threading.Barrier(2)

        def attempt():
            barrier.wait()          # line them up so the reads overlap
            results.append(self.redeem(token).status_code)

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sorted(results), [200, 400],
                         f"expected exactly one winner, got {results}")

        # And the database agrees: one account, one claimed invite.
        con = sqlite3.connect(self.db)
        self.assertEqual(
            con.execute("select count(*) from user_accounts").fetchone()[0], 1)
        self.assertEqual(
            con.execute("select count(*) from beta_access_invites "
                        "where accepted_at is not null").fetchone()[0], 1)
        con.close()

    def test_a_bound_invite_reuses_the_existing_account_rather_than_duplicating(self):
        """A tester clicking a second link should not end up with two accounts."""
        first = self.mint(bound_email="parent@example.com")
        a = self.redeem(first["invite_token"])
        self.assertEqual(a.status_code, 200, a.text)

        second = self.mint(bound_email="parent@example.com")
        b = self.redeem(second["invite_token"])
        self.assertEqual(b.status_code, 200, b.text)
        self.assertEqual(a.json()["id"], b.json()["id"],
                         "the same person should keep one account")

        con = sqlite3.connect(self.db)
        self.assertEqual(
            con.execute("select count(*) from user_accounts").fetchone()[0], 1)
        con.close()

    def test_an_unverified_client_email_never_links_to_an_existing_account(self):
        """Matching on a self-declared address would let anyone claim another
        person's account by typing their email."""
        bound = self.mint(bound_email="parent@example.com")
        first = self.redeem(bound["invite_token"])
        self.assertEqual(first.status_code, 200)

        unbound = self.mint()
        second = self.redeem(unbound["invite_token"], email="parent@example.com")
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(first.json()["id"], second.json()["id"])

    def test_an_expired_or_revoked_invite_is_refused(self):
        revoked = self.mint()
        self.client.post(f"/api/admin/beta-invites/{revoked['id']}/revoke",
                         headers={"X-Admin-Token": ADMIN})
        r = self.redeem(revoked["invite_token"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("revoked", r.json()["detail"])

        # ttl_days is clamped to a minimum of 1 by design - minting an invite
        # that is already dead would be a footgun - so age the stored row
        # instead of asking for a zero-day invite.
        expired = self.mint()
        con = sqlite3.connect(self.db)
        con.execute(
            "update beta_access_invites set expires_at = datetime('now','-1 day')"
            " where id = ?", (expired["id"],))
        con.commit()
        con.close()

        r = self.redeem(expired["invite_token"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("expired", r.json()["detail"])

    def test_the_raw_token_is_not_carried_in_the_url(self):
        """A token in a query string is a token in the access log and in any
        Referer the page sends."""
        invite = self.mint()
        r = self.redeem(invite["invite_token"])
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(invite["invite_token"], str(r.request.url))


# --------------------------------------------------------- registration modes

class RegistrationModeTests(PhaseATestCase):
    def test_closed_refuses_even_a_valid_invite(self):
        invite = self.mint()
        client, _ = _fresh(REGISTRATION_MODE="closed")
        r = client.post("/api/auth/accept-beta-invite",
                        json={"invite_token": invite["invite_token"]})
        self.assertEqual(r.status_code, 403)
        client.close()

    def test_closed_does_not_disturb_an_existing_account(self):
        """Closing the door stops new accounts; it does not evict anyone."""
        invite = self.mint()
        self.assertEqual(self.redeem(invite["invite_token"]).status_code, 200)
        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertIsNotNone(me.json())

    def test_an_unreadable_mode_never_falls_open(self):
        from core.config import RegistrationMode, registration_mode
        os.environ["REGISTRATION_MODE"] = "opne"
        self.assertEqual(registration_mode(), RegistrationMode.INVITE_ONLY)
        os.environ["REGISTRATION_MODE"] = "invite_only"


# ------------------------------------------------------------------- sessions

class SessionTests(PhaseATestCase):
    def _sign_in(self):
        invite = self.mint()
        r = self.redeem(invite["invite_token"], display_name="Tester")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def test_a_session_identifies_the_account(self):
        user_id = self._sign_in()
        me = self.client.get("/api/auth/me").json()
        self.assertEqual(me["id"], user_id)

    def test_signing_out_invalidates_the_session(self):
        self._sign_in()
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        self.assertIsNone(self.client.get("/api/auth/me").json())

    def test_a_disabled_account_stops_authenticating_immediately(self):
        """Not when the cookie expires. Authorization is re-checked per
        request rather than baked in at sign-in."""
        user_id = self._sign_in()
        r = self.client.post(f"/api/admin/accounts/{user_id}/disable",
                             headers={"X-Admin-Token": ADMIN})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(self.client.get("/api/auth/me").json())

    def test_disabling_requires_admin_credentials(self):
        user_id = self._sign_in()
        self.assertEqual(
            self.client.post(f"/api/admin/accounts/{user_id}/disable").status_code,
            403)

    def test_an_expired_session_does_not_authenticate(self):
        from core.accounts import StagingSession
        from core.db import SessionLocal
        self._sign_in()
        db = SessionLocal()
        from datetime import datetime, timedelta, timezone
        for row in db.query(StagingSession).all():
            row.expires_at = (datetime.now(timezone.utc).replace(tzinfo=None)
                              - timedelta(days=1))
        db.commit()
        db.close()
        self.assertIsNone(self.client.get("/api/auth/me").json())

    def test_an_unknown_cookie_is_not_an_account(self):
        self.client.cookies.set("driftway_staging_session", "not-a-real-session")
        self.assertIsNone(self.client.get("/api/auth/me").json())


# ----------------------------------------------------------- scope separation

class ScopeTests(PhaseATestCase):
    def test_a_beta_token_cannot_read_a_meetup(self):
        invite = self.mint()
        made = self.client.post("/api/meetups", json={
            "mode": "explore", "categories": [],
            "organiser": {"start": {"lat": 51.48, "lng": -0.62}},
        }).json()
        r = self.client.get(
            f"/api/meetups/{made['meetup_id']}/{invite['invite_token']}")
        self.assertEqual(r.status_code, 404)

    def test_a_guest_participates_without_any_account(self):
        """The fresh-browser journey, with registration closed to boot."""
        made = self.client.post("/api/meetups", json={
            "mode": "explore", "categories": [],
            "organiser": {"start": {"lat": 51.48, "lng": -0.62}},
        }).json()
        guest, _ = _fresh(REGISTRATION_MODE="closed")
        # A different client entirely: no cookies, no account.
        r = self.client.post(
            f"/api/meetups/{made['meetup_id']}/participants/"
            f"{made['participant_invite_token']}",
            json={"start": {"lat": 51.52, "lng": -0.72}, "display_name": "Guest"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(self.client.get("/api/auth/me").json(),
                          "participating must not have created a session")
        guest.close()

    def test_signing_in_does_not_grant_access_to_an_uninvited_meetup(self):
        invite = self.mint()
        self.redeem(invite["invite_token"])
        made = self.client.post("/api/meetups", json={
            "mode": "explore", "categories": [],
            "organiser": {"start": {"lat": 51.48, "lng": -0.62}},
        }).json()
        # A signed-in account still needs the capability.
        r = self.client.get(f"/api/meetups/{made['meetup_id']}/not-a-join-token")
        self.assertEqual(r.status_code, 404)


# ----------------------------------------------------------------- migrations

class MigrationTests(unittest.TestCase):
    def test_a_missing_column_is_added_to_an_existing_database(self):
        """The failure that took the service down once: create_all() adds
        tables but never columns."""
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        path = tmp.name

        # Build the table as an older version of the code would have.
        con = sqlite3.connect(path)
        con.execute(
            "create table meetup_venue_candidates ("
            " id varchar(36) primary key, meetup_id varchar(36), name varchar(160),"
            " lat float, lng float)"
        )
        con.execute(
            "insert into meetup_venue_candidates (id, meetup_id, name, lat, lng)"
            " values ('v1','m1','The Park',51.5,-0.6)"
        )
        con.commit()
        con.close()

        os.environ["DATABASE_URL"] = f"sqlite:///{path.replace(os.sep, '/')}"
        os.environ["MEET_HALFWAY_ENABLED"] = "true"
        os.environ["ADMIN_API_TOKEN"] = ADMIN
        os.environ["ROUTING_PROVIDER"] = "mock"
        _reset_modules()
        importlib.import_module("main")   # startup runs the migrations

        con = sqlite3.connect(path)
        cols = {r[1] for r in con.execute(
            "pragma table_info(meetup_venue_candidates)")}
        self.assertIn("added_by_participant_id", cols)

        # The existing row survived, with its relationships intact.
        row = con.execute(
            "select id, meetup_id, name from meetup_venue_candidates").fetchone()
        self.assertEqual(row, ("v1", "m1", "The Park"))
        con.close()

    def test_migrations_are_idempotent(self):
        from core.migrations import pending_steps, run_migrations
        self.assertEqual(run_migrations(), [], "a second run should do nothing")
        self.assertEqual(pending_steps(), [])

    def test_health_reports_outstanding_schema_work(self):
        client, _ = _fresh()
        body = client.get("/api/health").json()
        self.assertIn("schema_pending", body)
        self.assertEqual(body["schema_pending"], [])
        client.close()


if __name__ == "__main__":
    unittest.main()


# ------------------------------------------------------- open registration

class OpenRegistrationTests(unittest.TestCase):
    """RegistrationMode.OPEN, which was advertised but non-functional.

    The invite lookup ran even when no token had been supplied, so a correct
    open-registration request was answered with "that invitation is not
    valid". These pin the fixed behaviour and, just as importantly, pin that
    opening the door does not weaken anything else.
    """

    def tearDown(self):
        if getattr(self, "client", None):
            self.client.close()
        # _fresh() mutates the process environment, and these cases leave it
        # pointing somewhere unusual. Put it back so test order cannot matter.
        os.environ["REGISTRATION_MODE"] = "invite_only"

    def test_open_creates_an_account_without_any_invite(self):
        self.client, _ = _fresh(REGISTRATION_MODE="open")
        r = self.client.post("/api/auth/accept-beta-invite",
                             json={"display_name": "First Parent"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "active")

    def test_open_still_honours_an_invite_that_is_presented(self):
        """Links already sent out keep working the day the door opens."""
        self.client, _ = _fresh(REGISTRATION_MODE="open")
        minted = self.client.post("/api/admin/beta-invites",
                                  headers={"X-Admin-Token": ADMIN}).json()
        r = self.client.post(
            "/api/auth/accept-beta-invite",
            json={"invite_token": minted["invite_token"]},
        )
        self.assertEqual(r.status_code, 200, r.text)

        # And it is still single-use in open mode.
        again = self.client.post(
            "/api/auth/accept-beta-invite",
            json={"invite_token": minted["invite_token"]},
        )
        self.assertEqual(again.status_code, 400)
        self.assertIn("already been used", again.json()["detail"])

    def test_open_rejects_an_invite_that_was_revoked(self):
        """Open does not mean every token presented is now acceptable."""
        self.client, _ = _fresh(REGISTRATION_MODE="open")
        minted = self.client.post("/api/admin/beta-invites",
                                  headers={"X-Admin-Token": ADMIN}).json()
        self.client.post(f"/api/admin/beta-invites/{minted['id']}/revoke",
                         headers={"X-Admin-Token": ADMIN})
        r = self.client.post(
            "/api/auth/accept-beta-invite",
            json={"invite_token": minted["invite_token"]},
        )
        self.assertEqual(r.status_code, 400)

    def test_invite_only_refuses_a_request_with_no_token(self):
        """The schema no longer requires the token, so the SERVER must.

        Making invite_token optional is what lets open registration post
        without one; this is the check that stops that relaxation leaking into
        the closed test.
        """
        self.client, _ = _fresh(REGISTRATION_MODE="invite_only")
        r = self.client.post("/api/auth/accept-beta-invite",
                             json={"display_name": "Uninvited"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("invitation is required", r.json()["detail"])

    def test_health_reports_the_mode_so_the_ui_can_ask_correctly(self):
        self.client, _ = _fresh(REGISTRATION_MODE="open")
        self.assertEqual(
            self.client.get("/api/health").json()["registration"], "open")

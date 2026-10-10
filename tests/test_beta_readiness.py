"""
0.8, getting ready for the beta: feedback from any tab, and logs that keep
out what people search for.

Feedback about the app is its own record, attributed like route feedback:
to the account when signed in, and then exported and erased with it.
"""

import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from test_identity_auth0 import ADMIN, _fresh, _token  # noqa: E402


class AccessLogTests(unittest.TestCase):
    """Found writing the privacy policy: the access log held search text,
    positions and meetup link tokens."""

    def setUp(self):
        import main
        self.f = main._AccessLogPrivacy

    def test_search_text_and_position_are_dropped(self):
        self.assertEqual(self.f.clean("/api/search?q=SL4%201NJ&lat=51.48&lng=-0.61"),
                         "/api/search?…")

    def test_link_tokens_are_blanked_and_record_ids_kept(self):
        meetup = "3f2b8c1e-9a4d-4e6f-8b2a-1c3d5e7f9a0b"
        token = "Xq3vT9sLk2mN8pR4wY6zA1bC5dE7fG0hJ"
        self.assertEqual(self.f.clean(f"/api/meetups/{meetup}/{token}"),
                         f"/api/meetups/{meetup}/…")
        self.assertEqual(self.f.clean(f"/api/meetups/results/{token}"),
                         "/api/meetups/results/…")
        self.assertEqual(self.f.clean("/api/health"), "/api/health")

    def test_the_filter_rewrites_uvicorns_record(self):
        rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1,
                                '%s - "%s %s HTTP/%s" %d',
                                ("1.2.3.4:0", "GET", "/api/search?q=home", "1.1", 200), None)
        self.f().filter(rec)
        self.assertNotIn("home", rec.getMessage())
        self.assertIn("/api/search?…", rec.getMessage())


class AppFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.client, _ = _fresh()
        import routes.api as api
        api._app_feedback_caller = api.SlidingWindowLimiter()
        api._app_feedback_global = api.SlidingWindowLimiter()

    def tearDown(self):
        self.client.close()

    def admit(self, sub):
        minted = self.client.post("/api/admin/beta-invites",
                                  headers={"X-Admin-Token": ADMIN}).json()
        token = _token(sub=sub)
        self.client.post("/api/auth/accept-beta-invite",
                         json={"invite_token": minted["invite_token"]},
                         headers={"Authorization": f"Bearer {token}"})
        return {"Authorization": f"Bearer {token}"}

    def send(self, headers=None, **kw):
        body = {"context": "walk", "message": "The map is lovely", "app_version": "0.8.0",
                "build": "abc1234", "owner": "device-1"}
        body.update(kw)
        return self.client.post("/api/feedback/app", json=body, headers=headers or {})

    def test_any_tab_can_send_feedback_without_an_account(self):
        r = self.send()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["ok"])

    def test_it_must_say_something_and_not_too_much(self):
        self.assertEqual(self.send(message="").status_code, 422)
        self.assertEqual(self.send(message="x" * 2001).status_code, 422)
        self.assertEqual(self.send(context="elsewhere").status_code, 422)

    def test_signed_in_feedback_is_exported_and_erased_with_the_account(self):
        auth = self.admit("auth0|fb")
        self.assertEqual(self.send(headers=auth, message="Checkpoint picker is great").status_code,
                         200)
        export = self.client.get("/api/account/export", headers=auth).json()
        self.assertEqual([f["message"] for f in export["app_feedback"]],
                         ["Checkpoint picker is great"])
        gone = self.client.delete("/api/account", headers=auth).json()
        self.assertEqual(gone["removed"]["app_feedback"], 1)

    def test_it_is_metered_per_sender(self):
        codes = [self.send().status_code for _ in range(12)]
        self.assertIn(429, codes)

    def test_the_message_is_not_logged(self):
        with self.assertLogs("driftway", level="INFO") as logs:
            self.send(message="my address is 1 Private Road")
        self.assertNotIn("Private Road", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()


class ProviderErrorLogTests(unittest.TestCase):
    def test_coordinates_in_a_provider_error_are_blanked(self):
        from core.router import _no_numbers
        self.assertEqual(_no_numbers("No route between points (51.4816, -0.6105)"),
                         "No route between points (#, #)")


class OwnDataTests(unittest.TestCase):
    """Play's account-deletion rules, and plain fairness: downloading or
    deleting your own data must not depend on your account being active."""

    def setUp(self):
        self.client, _ = _fresh()

    def tearDown(self):
        self.client.close()

    def _admitted(self, sub):
        minted = self.client.post("/api/admin/beta-invites",
                                  headers={"X-Admin-Token": ADMIN}).json()
        token = _token(sub=sub)
        auth = {"Authorization": f"Bearer {token}"}
        self.client.post("/api/auth/accept-beta-invite",
                         json={"invite_token": minted["invite_token"]}, headers=auth)
        return auth

    def test_a_disabled_account_can_still_download_and_delete_itself(self):
        auth = self._admitted("auth0|gone")
        me = self.client.get("/api/account/export", headers=auth).json()["account"]
        self.client.post(f"/api/admin/accounts/{me['id']}/disable",
                         headers={"X-Admin-Token": ADMIN})
        # Disabled: no features...
        self.assertIsNone(self.client.get("/api/auth/me", headers=auth).json())
        # ...but its own data is still its owner's.
        self.assertEqual(self.client.get("/api/account/export", headers=auth).status_code, 200)
        gone = self.client.delete("/api/account", headers=auth)
        self.assertEqual(gone.status_code, 200)
        self.assertEqual(self.client.get("/api/account/export", headers=auth).status_code, 401)

    def test_deletion_needs_no_new_invitation(self):
        auth = self._admitted("auth0|leaving")
        self.assertEqual(self.client.delete("/api/account", headers=auth).status_code, 200)

    def test_someone_else_cannot_delete_by_being_signed_in(self):
        self._admitted("auth0|owner")
        stranger = {"Authorization": f"Bearer {_token(sub='auth0|stranger')}"}
        self.assertEqual(self.client.delete("/api/account", headers=stranger).status_code, 401)

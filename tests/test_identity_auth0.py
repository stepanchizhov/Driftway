"""
Auth0 verification, export and erasure.

Tokens here are signed with a throwaway RSA key and verified against a stubbed
JWKS, so the real cryptographic path runs — signature, issuer, audience,
expiry, algorithm — without a network call or a tenant. What this does NOT
prove is a live Auth0 integration; that needs a configured tenant and a real
sign-in, and is tracked separately as STAGED.
"""

import importlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

BACKEND = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

DOMAIN = "naploop-test.uk.auth0.com"
AUDIENCE = "https://api.naploop.test"
ADMIN = "auth0-tests-admin"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KID = "test-key-1"


def _token(sub="auth0|abc123", *, aud=AUDIENCE, iss=None, email="parent@example.com",
           email_verified=True, expired=False, alg="RS256"):
    now = datetime.now(timezone.utc)
    claims = {
        "sub": sub,
        "aud": aud,
        "iss": iss or f"https://{DOMAIN}/",
        "iat": int(now.timestamp()),
        "exp": int((now - timedelta(hours=1) if expired
                    else now + timedelta(hours=1)).timestamp()),
        "email": email,
        "email_verified": email_verified,
    }
    return jwt.encode(claims, _KEY, algorithm=alg, headers={"kid": _KID})


class _StubJWKClient:
    """Stands in for the network call to the tenant's JWKS endpoint."""

    def __init__(self, *_a, **_kw):
        pass

    def get_signing_key_from_jwt(self, _token):
        class _K:
            key = _KEY.public_key()
        return _K()


def _reset_modules():
    for name in [m for m in sys.modules
                 if m == "main" or m.startswith(("core.", "routes."))]:
        sys.modules.pop(name, None)


def _fresh(configured=True, **env):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp.name.replace(os.sep, '/')}"
    os.environ["MEET_HALFWAY_ENABLED"] = "true"
    os.environ["REGISTRATION_MODE"] = env.get("REGISTRATION_MODE", "invite_only")
    os.environ["ADMIN_API_TOKEN"] = ADMIN
    os.environ["ROUTING_PROVIDER"] = "mock"
    if configured:
        os.environ["AUTH0_DOMAIN"] = DOMAIN
        os.environ["AUTH0_AUDIENCE"] = AUDIENCE
    else:
        os.environ.pop("AUTH0_DOMAIN", None)
        os.environ.pop("AUTH0_AUDIENCE", None)
    _reset_modules()
    import core.identity as identity
    identity._jwks_client = _StubJWKClient()
    main = importlib.import_module("main")
    # main imports identity; make sure the stub survives.
    sys.modules["core.identity"]._jwks_client = _StubJWKClient()
    from fastapi.testclient import TestClient
    return TestClient(main.app), tmp.name


class TokenVerificationTests(unittest.TestCase):
    def setUp(self):
        self.client, _ = _fresh()
        import core.identity as identity
        self.identity = identity

    def tearDown(self):
        self.client.close()

    def test_a_properly_signed_token_verifies(self):
        v = self.identity.verify_access_token(_token())
        self.assertEqual(v.subject, "auth0|abc123")
        self.assertTrue(v.email_verified)

    def test_an_expired_token_is_refused(self):
        with self.assertRaises(self.identity.IdentityError) as ctx:
            self.identity.verify_access_token(_token(expired=True))
        self.assertIn("expired", str(ctx.exception).lower())

    def test_a_token_for_another_audience_is_refused(self):
        with self.assertRaises(self.identity.IdentityError) as ctx:
            self.identity.verify_access_token(_token(aud="https://someone-else"))
        self.assertIn("different application", str(ctx.exception))

    def test_a_token_from_another_issuer_is_refused(self):
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_access_token(
                _token(iss="https://evil.example.com/"))

    def test_an_unsigned_token_is_refused(self):
        """alg=none is the classic JWT bypass. The algorithm is pinned."""
        forged = jwt.encode({"sub": "auth0|attacker", "aud": AUDIENCE,
                             "iss": f"https://{DOMAIN}/"},
                            key="", algorithm="none")
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_access_token(forged)

    def test_garbage_is_refused_without_leaking_detail(self):
        with self.assertRaises(self.identity.IdentityError) as ctx:
            self.identity.verify_access_token("not-a-token")
        self.assertIn("could not be verified", str(ctx.exception))

    def test_nothing_verifies_when_no_tenant_is_configured(self):
        client, _ = _fresh(configured=False)
        import core.identity as identity
        self.assertFalse(identity.is_configured())
        with self.assertRaises(identity.IdentityError):
            identity.verify_access_token(_token())
        client.close()


class AdmissionTests(unittest.TestCase):
    """A verified sign-in is not admission. An invitation is."""

    def setUp(self):
        self.client, self.db = _fresh()

    def tearDown(self):
        self.client.close()

    def mint(self, **kw):
        return self.client.post("/api/admin/beta-invites",
                                headers={"X-Admin-Token": ADMIN},
                                params=kw).json()

    def test_a_valid_token_alone_does_not_create_an_account(self):
        r = self.client.post("/api/auth/session",
                             headers={"Authorization": f"Bearer {_token()}"})
        self.assertEqual(r.status_code, 403)
        self.assertIn("invitation", r.json()["detail"])

    def test_an_invitation_plus_a_verified_identity_creates_one(self):
        invite = self.mint()
        r = self.client.post(
            "/api/auth/accept-beta-invite",
            json={"invite_token": invite["invite_token"], "display_name": "Stepan"},
            headers={"Authorization": f"Bearer {_token()}"},
        )
        self.assertEqual(r.status_code, 200, r.text)

        # And the same identity is now recognised without the invite.
        me = self.client.post("/api/auth/session",
                              headers={"Authorization": f"Bearer {_token()}"})
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["id"], r.json()["id"])

    def test_an_invitation_without_a_verified_identity_is_refused(self):
        """With a provider configured, the invite alone is not enough."""
        invite = self.mint()
        r = self.client.post("/api/auth/accept-beta-invite",
                             json={"invite_token": invite["invite_token"]})
        self.assertEqual(r.status_code, 401)

    def test_no_staging_cookie_is_issued_once_a_provider_is_configured(self):
        """Two doors, one of them unverified, is one door too many."""
        invite = self.mint()
        r = self.client.post(
            "/api/auth/accept-beta-invite",
            json={"invite_token": invite["invite_token"]},
            headers={"Authorization": f"Bearer {_token()}"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("driftway_staging_session", r.cookies)

    def test_a_different_person_gets_a_different_account(self):
        for sub in ("auth0|first", "auth0|second"):
            invite = self.mint()
            r = self.client.post(
                "/api/auth/accept-beta-invite",
                json={"invite_token": invite["invite_token"]},
                headers={"Authorization": f"Bearer {_token(sub=sub)}"},
            )
            self.assertEqual(r.status_code, 200, r.text)

        a = self.client.post("/api/auth/session", headers={
            "Authorization": f"Bearer {_token(sub='auth0|first')}"}).json()
        b = self.client.post("/api/auth/session", headers={
            "Authorization": f"Bearer {_token(sub='auth0|second')}"}).json()
        self.assertNotEqual(a["id"], b["id"])

    def test_a_disabled_account_cannot_sign_in(self):
        invite = self.mint()
        created = self.client.post(
            "/api/auth/accept-beta-invite",
            json={"invite_token": invite["invite_token"]},
            headers={"Authorization": f"Bearer {_token()}"},
        ).json()
        self.client.post(f"/api/admin/accounts/{created['id']}/disable",
                         headers={"X-Admin-Token": ADMIN})
        r = self.client.post("/api/auth/session",
                             headers={"Authorization": f"Bearer {_token()}"})
        self.assertEqual(r.status_code, 403)

    def test_health_says_which_identity_mechanism_is_live(self):
        self.assertEqual(self.client.get("/api/health").json()["identity"], "auth0")
        client, _ = _fresh(configured=False)
        self.assertEqual(client.get("/api/health").json()["identity"], "staging")
        client.close()


class ExportAndErasureTests(unittest.TestCase):
    def setUp(self):
        self.client, self.db = _fresh()
        invite = self.client.post("/api/admin/beta-invites",
                                  headers={"X-Admin-Token": ADMIN}).json()
        self.account = self.client.post(
            "/api/auth/accept-beta-invite",
            json={"invite_token": invite["invite_token"], "display_name": "Stepan"},
            headers={"Authorization": f"Bearer {_token()}"},
        ).json()
        self.auth = {"Authorization": f"Bearer {_token()}"}

    def tearDown(self):
        self.client.close()

    def test_the_export_contains_your_own_exact_origin(self):
        """Yours, and the sensitivity is why you are entitled to it."""
        made = self.client.post("/api/meetups", json={
            "mode": "explore", "categories": [],
            "organiser": {"start": {"lat": 51.4857, "lng": -0.6214}},
        }, headers=self.auth).json()
        self.assertIn("meetup_id", made, made)

        dump = self.client.get("/api/account/export", headers=self.auth)
        self.assertEqual(dump.status_code, 200, dump.text)
        body = dump.json()
        self.assertEqual(body["account"]["display_name"], "Stepan")
        self.assertIn("not_included", body)

    def test_the_export_needs_authentication(self):
        self.assertEqual(self.client.get("/api/account/export").status_code, 401)

    def test_erasure_removes_the_account(self):
        r = self.client.delete("/api/account", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        after = self.client.post("/api/auth/session", headers=self.auth)
        self.assertEqual(after.status_code, 403,
                         "the identity should no longer resolve to an account")

    def test_erasure_needs_authentication(self):
        self.assertEqual(self.client.delete("/api/account").status_code, 401)


class RetentionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.client, self.db = _fresh()

    def tearDown(self):
        self.client.close()

    def test_the_stated_policy_is_what_the_code_does(self):
        from core.retention import INACTIVE_ACCOUNT_RETENTION_DAYS
        self.assertEqual(INACTIVE_ACCOUNT_RETENTION_DAYS, 365)

    def test_a_meetup_is_purged_once_it_is_well_past(self):
        from core.db import SessionLocal
        from core.meetups import MeetupSession
        from core.retention import purge_expired_meetups

        made = self.client.post("/api/meetups", json={
            "mode": "explore", "categories": [],
            "organiser": {"start": {"lat": 51.4857, "lng": -0.6214}},
        }).json()

        db = SessionLocal()
        row = db.get(MeetupSession, made["meetup_id"])
        row.scheduled_at = datetime.now(timezone.utc).replace(tzinfo=None) \
            - timedelta(days=90)
        db.commit()

        purged = purge_expired_meetups(db)
        self.assertIn(made["meetup_id"], purged)
        self.assertIsNone(db.get(MeetupSession, made["meetup_id"]))
        db.close()

    def test_an_upcoming_meetup_is_never_purged(self):
        from core.db import SessionLocal
        from core.meetups import MeetupSession
        from core.retention import purge_expired_meetups

        made = self.client.post("/api/meetups", json={
            "mode": "explore", "categories": [],
            "organiser": {"start": {"lat": 51.4857, "lng": -0.6214}},
        }).json()
        db = SessionLocal()
        row = db.get(MeetupSession, made["meetup_id"])
        row.scheduled_at = datetime.now(timezone.utc).replace(tzinfo=None) \
            + timedelta(days=3)
        db.commit()

        self.assertEqual(purge_expired_meetups(db), [])
        self.assertIsNotNone(db.get(MeetupSession, made["meetup_id"]))
        db.close()

    def test_an_active_account_is_never_purged(self):
        from core.db import SessionLocal
        from core.retention import purge_inactive_accounts
        invite = self.client.post("/api/admin/beta-invites",
                                  headers={"X-Admin-Token": ADMIN}).json()
        self.client.post(
            "/api/auth/accept-beta-invite",
            json={"invite_token": invite["invite_token"]},
            headers={"Authorization": f"Bearer {_token()}"},
        )
        db = SessionLocal()
        self.assertEqual(purge_inactive_accounts(db), [])
        db.close()


if __name__ == "__main__":
    unittest.main()

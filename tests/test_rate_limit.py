"""
Inbound limits on the endpoint that spends money.

`/api/generate` is the only place an anonymous stranger can run up a provider
bill, so these cover the ways a limiter is usually got around rather than the
happy path: varying client-supplied request fields, forging a forwarded-for
header, and many callers arriving at once rather than one caller repeating.
"""

import importlib
import os
import sys
import tempfile
import unittest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

LOOP = {
    "start": {"lat": 51.4857, "lng": -0.6214},
    "target_minutes": 30,
    "road_profile": "mixed",
    "mode": "loop",
}


#: Set by these tests and nothing else. _fresh() and tearDown both clear them,
#: because os.environ outlives the test: leaving GENERATE_GLOBAL_PER_HOUR=1
#: behind silently throttled an unrelated module later in the run.
TUNABLES = ("GENERATE_PER_MINUTE", "GENERATE_PER_HOUR",
            "GENERATE_GLOBAL_PER_HOUR", "TRUSTED_PROXY_COUNT")


def _clear_tunables():
    for key in TUNABLES:
        os.environ.pop(key, None)


class RateLimitTestCase(unittest.TestCase):
    """Closes the client and puts the environment back, whatever happened."""

    client = None

    def tearDown(self):
        if self.client is not None:
            self.client.close()
            self.client = None
        _clear_tunables()


def _fresh(**env):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp.name.replace(os.sep, '/')}"
    os.environ["ROUTING_PROVIDER"] = "mock"
    os.environ["MEET_HALFWAY_ENABLED"] = "true"
    _clear_tunables()
    os.environ.update(env)
    for name in [m for m in sys.modules
                 if m == "main" or m.startswith(("core.", "routes."))]:
        sys.modules.pop(name, None)
    main = importlib.import_module("main")
    from fastapi.testclient import TestClient
    return TestClient(main.app)


class CallerLimitTests(RateLimitTestCase):
    def test_a_caller_is_cut_off_after_the_allowance(self):
        self.client = _fresh(GENERATE_PER_MINUTE="3")
        codes = [self.client.post("/api/generate", json=LOOP).status_code
                 for _ in range(5)]
        self.assertEqual(codes[:3], [200, 200, 200])
        self.assertEqual(codes[3], 429)

    def test_the_refusal_says_how_long_to_wait(self):
        self.client = _fresh(GENERATE_PER_MINUTE="1")
        self.client.post("/api/generate", json=LOOP)
        r = self.client.post("/api/generate", json=LOOP)
        self.assertEqual(r.status_code, 429)
        self.assertIn("Retry-After", r.headers)
        self.assertGreaterEqual(int(r.headers["Retry-After"]), 1)
        # A human-readable reason, not a bare code.
        self.assertIn("try again", r.json()["detail"].lower())

    def test_varying_the_request_body_does_not_reset_the_limit(self):
        """Nothing the caller varies in the body may reset the allowance.

        The per-device id is client-chosen; so is every other body field. The
        key must come from the account or the address and nowhere else.
        """
        self.client = _fresh(GENERATE_PER_MINUTE="2")
        self.client.post("/api/generate", json={**LOOP, "preferred_navigation": "google_maps"})
        self.client.post("/api/generate", json={**LOOP, "preferred_navigation": "waze"})
        r = self.client.post("/api/generate", json={**LOOP, "preferred_navigation": "apple_maps"})
        self.assertEqual(r.status_code, 429)

    def test_a_forwarded_header_is_ignored_when_no_proxy_is_trusted(self):
        """Otherwise one line of header spoofing buys an unlimited allowance."""
        self.client = _fresh(GENERATE_PER_MINUTE="2")
        for i in range(2):
            self.client.post("/api/generate", json=LOOP,
                             headers={"X-Forwarded-For": f"9.9.9.{i}"})
        r = self.client.post("/api/generate", json=LOOP,
                             headers={"X-Forwarded-For": "9.9.9.99"})
        self.assertEqual(r.status_code, 429)

    def test_a_forwarded_header_is_honoured_when_a_proxy_is_trusted(self):
        """On Render the real address only arrives this way."""
        self.client = _fresh(GENERATE_PER_MINUTE="2", TRUSTED_PROXY_COUNT="1")
        for _ in range(2):
            self.client.post("/api/generate", json=LOOP,
                             headers={"X-Forwarded-For": "203.0.113.5"})
        blocked = self.client.post("/api/generate", json=LOOP,
                                   headers={"X-Forwarded-For": "203.0.113.5"})
        self.assertEqual(blocked.status_code, 429)
        # A genuinely different client is unaffected.
        other = self.client.post("/api/generate", json=LOOP,
                                 headers={"X-Forwarded-For": "203.0.113.6"})
        self.assertEqual(other.status_code, 200)


class ServiceCeilingTests(RateLimitTestCase):
    def test_the_service_ceiling_holds_when_many_callers_arrive(self):
        """Per-caller limits do nothing about the link being posted somewhere busy."""
        self.client = _fresh(GENERATE_PER_MINUTE="50",
                             GENERATE_GLOBAL_PER_HOUR="3",
                             TRUSTED_PROXY_COUNT="1")
        codes = [
            self.client.post("/api/generate", json=LOOP,
                             headers={"X-Forwarded-For": f"198.51.100.{i}"}).status_code
            for i in range(5)
        ]
        self.assertEqual(codes[:3], [200, 200, 200])
        self.assertEqual(codes[3], 429)

    def test_the_service_message_differs_from_the_personal_one(self):
        self.client = _fresh(GENERATE_GLOBAL_PER_HOUR="1")
        self.client.post("/api/generate", json=LOOP)
        r = self.client.post("/api/generate", json=LOOP)
        self.assertEqual(r.status_code, 429)
        self.assertIn("at its limit", r.json()["detail"])


class UnmeteredSurfaceTests(RateLimitTestCase):
    """Limiting the expensive endpoint must not limit the cheap ones."""

    def test_health_is_not_rate_limited(self):
        self.client = _fresh(GENERATE_PER_MINUTE="1")
        self.client.post("/api/generate", json=LOOP)
        self.client.post("/api/generate", json=LOOP)
        for _ in range(5):
            self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_an_unverifiable_token_still_plans_a_route(self):
        """Generate owns nothing, so a bad token falls back rather than refusing."""
        self.client = _fresh()
        r = self.client.post("/api/generate", json=LOOP,
                             headers={"Authorization": "Bearer nonsense"})
        self.assertEqual(r.status_code, 200, r.text)

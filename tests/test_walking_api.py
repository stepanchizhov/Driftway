"""
The walking endpoint's gates.

Access policy: since 11 Oct 2026 walks are open to everyone (WALKS_ACCESS
unset or "everyone"); WALKS_ACCESS=admitted restores the beta-only gate. Either
way they do not exist at all while WALKING_ENABLED is off.
These check each gate holds on its own - the flag, admission, credentials,
storage - and that the experiment leaves no trace when it is switched off.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from test_identity_auth0 import ADMIN, _fresh, _token  # noqa: E402

PRAM = {"profile": "pram", "minutes": 30,
        "pram": {"wheels": "standard", "width_cm": 60}}
CARRIER = {"profile": "carrier",
           "carrier": {"kind": "soft", "child_kg": 9, "carrier_kg": 1.2,
                       "luggage_kg": 3, "luggage_with": "companion"}}


def auth(token):
    return {"Authorization": f"Bearer {token}"}


class WalkingApiTestCase(unittest.TestCase):
    flag = "true"

    def setUp(self):
        os.environ["WALKING_ENABLED"] = self.flag
        self.client, _ = _fresh()

    def tearDown(self):
        self.client.close()
        os.environ.pop("WALKING_ENABLED", None)

    def admit(self, sub="auth0|walker"):
        minted = self.client.post("/api/admin/beta-invites",
                                  headers={"X-Admin-Token": ADMIN}).json()
        token = _token(sub=sub)
        r = self.client.post("/api/auth/accept-beta-invite",
                             json={"invite_token": minted["invite_token"]},
                             headers=auth(token))
        self.assertEqual(r.status_code, 200, r.text)
        return token


class FlagOffTests(WalkingApiTestCase):
    flag = "false"

    def test_the_endpoint_does_not_exist_when_off(self):
        """Even for an admitted account: off means off."""
        token = self.admit()
        r = self.client.post("/api/walks/assess", json=PRAM, headers=auth(token))
        self.assertEqual(r.status_code, 404)

    def test_health_says_it_is_off_so_no_entry_point_is_shown(self):
        self.assertFalse(self.client.get("/api/health").json()["walking"])

    def test_driving_is_unaffected_when_off(self):
        r = self.client.post("/api/generate", json={
            "start": {"lat": 51.4857, "lng": -0.6214}, "target_minutes": 30})
        self.assertEqual(r.status_code, 200)


class OpenAccessTests(WalkingApiTestCase):
    """The default since 11 Oct 2026."""

    def test_an_anonymous_request_gets_the_walks(self):
        r = self.client.post("/api/walks/assess", json=PRAM)
        self.assertEqual(r.status_code, 200, r.text)

    def test_signed_in_without_an_invitation_gets_the_walks(self):
        r = self.client.post("/api/walks/assess", json=PRAM,
                             headers=auth(_token(sub="auth0|stranger")))
        self.assertEqual(r.status_code, 200, r.text)

    def test_an_expired_token_is_still_refused(self):
        """Not quietly treated as signed out: the app asks them to sign in."""
        r = self.client.post("/api/walks/assess", json=PRAM,
                             headers=auth(_token(sub="auth0|walker", expired=True)))
        self.assertEqual(r.status_code, 401)

    def test_a_misspelled_setting_closes_rather_than_opens(self):
        os.environ["WALKS_ACCESS"] = "evryone"
        try:
            r = self.client.post("/api/walks/assess", json=PRAM)
        finally:
            os.environ.pop("WALKS_ACCESS", None)
        self.assertEqual(r.status_code, 403)


class AdmissionTests(WalkingApiTestCase):
    """WALKS_ACCESS=admitted: the 14 Sep beta-only policy, kept for later."""

    def setUp(self):
        super().setUp()
        os.environ["WALKS_ACCESS"] = "admitted"

    def tearDown(self):
        os.environ.pop("WALKS_ACCESS", None)
        super().tearDown()

    def test_an_anonymous_request_is_refused(self):
        r = self.client.post("/api/walks/assess", json=PRAM)
        self.assertEqual(r.status_code, 403)
        self.assertIn("closed beta", r.json()["detail"])

    def test_signed_in_but_not_invited_is_refused(self):
        """Signing in is identity; the invitation is admission."""
        r = self.client.post("/api/walks/assess", json=PRAM,
                             headers=auth(_token(sub="auth0|stranger")))
        self.assertEqual(r.status_code, 403)

    def test_an_expired_token_is_refused_not_demoted(self):
        r = self.client.post("/api/walks/assess", json=PRAM,
                             headers=auth(_token(sub="auth0|walker", expired=True)))
        self.assertEqual(r.status_code, 401)

    def test_an_admitted_account_gets_the_walks(self):
        token = self.admit()
        r = self.client.post("/api/walks/assess", json=PRAM, headers=auth(token))
        self.assertEqual(r.status_code, 200, r.text)
        walks = r.json()["walks"]
        self.assertGreaterEqual(len(walks), 2)
        self.assertTrue(all("verdict" in w and "sections" in w for w in walks))

    def test_health_says_it_is_on(self):
        self.assertTrue(self.client.get("/api/health").json()["walking"])


class ProfileResponseTests(WalkingApiTestCase):
    def setUp(self):
        super().setUp()
        self.token = self.admit()

    def post(self, body):
        r = self.client.post("/api/walks/assess", json=body, headers=auth(self.token))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_pram_and_carrier_get_different_answers_for_the_same_walks(self):
        pram = {w["id"]: w["verdict"] for w in self.post(PRAM)["walks"]}
        carrier = {w["id"]: w["verdict"] for w in self.post(CARRIER)["walks"]}
        self.assertEqual(set(pram), set(carrier))
        self.assertNotEqual(pram, carrier)

    def test_a_soft_carrier_gets_ticks_with_its_source(self):
        g = self.post(CARRIER)["guidance"][0]
        self.assertIn("TICKS", g["title"])
        self.assertIn("lullabytrust.org.uk", g["url"])
        self.assertTrue(g["reviewed"])

    def test_a_framed_carrier_is_pointed_at_its_own_instructions(self):
        body = {**CARRIER, "carrier": {**CARRIER["carrier"], "kind": "framed"}}
        g = self.post(body)["guidance"][0]
        self.assertIn("manufacturer", " ".join(g["points"]).lower())

    def test_luggage_carried_by_a_companion_is_left_out_of_the_load(self):
        self.assertEqual(self.post(CARRIER)["carried_kg"], 10.2)

    def test_the_handoff_limitation_is_stated(self):
        self.assertIn("will not follow this walk", self.post(PRAM)["handoff"])

    def test_every_walk_names_its_sources(self):
        for w in self.post(PRAM)["walks"]:
            ids = {s["id"] for s in w["sources"]}
            self.assertIn("osm", ids)

    def test_the_request_leaves_nothing_behind(self):
        """Equipment and load are used for one assessment and never written."""
        from core.db import Base, SessionLocal
        s = SessionLocal()
        before = {t.name: s.execute(t.select()).fetchall().__len__()
                  for t in Base.metadata.sorted_tables}
        self.post(CARRIER)
        after = {t.name: s.execute(t.select()).fetchall().__len__()
                 for t in Base.metadata.sorted_tables}
        s.close()
        self.assertEqual(before, after)


class PaceTests(WalkingApiTestCase):
    """The parent's own walking pace (founder request, 11 Oct 2026)."""

    def minutes(self, **extra):
        r = self.client.post("/api/walks/assess", json={**PRAM, **extra})
        self.assertEqual(r.status_code, 200, r.text)
        return {w["id"]: w for w in r.json()["walks"]}

    def test_a_faster_pace_makes_every_walk_quicker(self):
        """The whole walk takes less time. A walk shortened to fit the time
        asked for still fits it; it just turns back further along."""
        full = lambda w: w["fit"]["full_minutes"] if w.get("fit") else w["minutes"]
        usual, brisk = self.minutes(), self.minutes(pace_kmh=5)
        for walk_id, w in usual.items():
            self.assertLess(full(brisk[walk_id]), full(w), walk_id)
            if w.get("fit") and w["fit"].get("turn_back_at_m"):
                self.assertGreaterEqual(brisk[walk_id]["fit"]["turn_back_at_m"],
                                        w["fit"]["turn_back_at_m"], walk_id)

    def test_the_card_states_the_pace_used(self):
        w = next(iter(self.minutes(pace_kmh=4.5).values()))
        self.assertIn("About 4.5 km/h", w["assumptions"])
        w = next(iter(self.minutes().values()))
        self.assertIn("About 4 km/h", w["assumptions"])

    def test_the_pace_does_not_outlive_its_request(self):
        before = self.minutes()
        self.minutes(pace_kmh=6)
        self.assertEqual(self.minutes(), before)

    def test_impossible_paces_are_refused(self):
        for bad in (0, 1.5, 7.5, "fast"):
            r = self.client.post("/api/walks/assess", json={**PRAM, "pace_kmh": bad})
            self.assertEqual(r.status_code, 422, bad)

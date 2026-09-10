"""
Meet Halfway, Milestone 2: the pooled-candidate planner.

Fairness is tested against `score_venue`/`rank_venues` directly, because that is
where the judgement lives and a pure function can be pinned to exact minutes.
The endpoints are then tested for wiring, with the deterministic mock router.
"""

import importlib
import os
import sys
import tempfile
import unittest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from backend.core.meetup_ranking import (  # noqa: E402
    ParticipantNeed,
    rank_venues,
    score_venue,
)
from backend.core.meetup_schemas import group_fit_label  # noqa: E402

A, B = "participant-a", "participant-b"

# Windsor-area origins, plus venues between them.
ORIGIN_A = {"lat": 51.4857, "lng": -0.6214}
ORIGIN_B = {"lat": 51.5216, "lng": -0.7205}
VENUE_1 = {"lat": 51.50, "lng": -0.67}
VENUE_2 = {"lat": 51.51, "lng": -0.70}


def _needs(a_max=None, a_pref=None, a_tol=None, b_max=None, b_pref=None, b_tol=None):
    return [
        ParticipantNeed(A, preferred_minutes=a_pref, tolerance_minutes=a_tol,
                        max_minutes=a_max),
        ParticipantNeed(B, preferred_minutes=b_pref, tolerance_minutes=b_tol,
                        max_minutes=b_max),
    ]


def _score(index, a_minutes, b_minutes, needs, **kw):
    return score_venue(index, {A: a_minutes, B: b_minutes}, needs, **kw)


# ---------------------------------------------------------------- fairness

class FairnessTests(unittest.TestCase):
    def test_25_vs_28_is_more_even_than_25_vs_40(self):
        needs = _needs()
        even = _score(0, 25.0, 28.0, needs)
        uneven = _score(1, 25.0, 40.0, needs)

        self.assertEqual(even.spread, 3.0)
        self.assertEqual(uneven.spread, 15.0)
        ranked = rank_venues([uneven, even], needs)
        self.assertEqual(ranked.ordered[0].venue_index, 0,
                         "the more even option should rank first")

    def test_90_vs_120_is_a_thirty_minute_spread_not_a_small_relative_gap(self):
        """The parent doing the extra half hour is not consoled by a ratio."""
        score = _score(0, 90.0, 120.0, _needs())
        self.assertEqual(score.spread, 30.0)
        self.assertEqual(score.max_burden, 120.0)
        self.assertEqual(group_fit_label(score.spread), "Significant difference")

    def test_an_explicit_maximum_of_30_rejects_a_35_minute_candidate(self):
        needs = _needs(a_max=30)
        over = _score(0, 35.0, 20.0, needs)
        self.assertEqual(over.hard_violations, 1)
        self.assertTrue(over.travel[0]["exceeds_maximum"])

        result = rank_venues([over], needs)
        self.assertTrue(result.no_fit)
        self.assertIn("maximum drive time", result.notice)

    def test_a_preferred_time_can_outrank_a_shorter_drive(self):
        """Preferred 40 with max 55: a 43-minute venue should beat a 25-minute
        one. Shortest is not the same as best - a parent who asked for 40
        minutes may be planning around a nap."""
        needs = _needs(a_max=55, a_pref=40, a_tol=10,
                       b_max=55, b_pref=40, b_tol=10)
        near_preferred = _score(0, 43.0, 41.0, needs)
        much_shorter = _score(1, 25.0, 24.0, needs)

        result = rank_venues([much_shorter, near_preferred], needs)
        self.assertEqual(result.ordered[0].venue_index, 0)
        self.assertFalse(result.no_fit)

    def test_a_preferred_time_is_not_a_hard_ban(self):
        """Missing a preference costs ranking position, never eligibility."""
        needs = _needs(a_pref=30, a_tol=5)
        miss = _score(0, 55.0, 55.0, needs)
        self.assertEqual(miss.hard_violations, 0)
        result = rank_venues([miss], needs)
        self.assertFalse(result.no_fit)
        self.assertEqual(len(result.ordered), 1)

    def test_a_participant_with_no_maximum_never_blocks_a_candidate(self):
        needs = _needs(a_max=None, b_max=None)
        long_drive = _score(0, 95.0, 88.0, needs)
        self.assertEqual(long_drive.hard_violations, 0)
        result = rank_venues([long_drive], needs)
        self.assertFalse(result.no_fit)
        # And the real minutes are still reported, not hidden behind a label.
        self.assertEqual(result.ordered[0].travel[0]["direct_minutes"], 95.0)

    def test_tolerance_scales_the_preference_penalty(self):
        """"35 give or take 15" should not be judged like "35 give or take 5"."""
        tight = _score(0, 50.0, 50.0, _needs(a_pref=35, a_tol=5, b_pref=35, b_tol=5))
        loose = _score(0, 50.0, 50.0, _needs(a_pref=35, a_tol=15, b_pref=35, b_tol=15))
        self.assertGreater(tight.preferred_penalty, loose.preferred_penalty)

    def test_a_hard_maximum_outranks_a_better_rating(self):
        """Gated ordering: a five-star venue cannot buy its way past someone's
        stated limit."""
        needs = _needs(a_max=30)
        within = _score(0, 28.0, 28.0, needs, provider_rating=2.0)
        over = _score(1, 45.0, 20.0, needs, provider_rating=5.0)
        result = rank_venues([over, within], needs)
        self.assertEqual(result.ordered[0].venue_index, 0)


class FallbackTests(unittest.TestCase):
    def test_no_candidate_fitting_every_maximum_returns_a_structured_no_fit(self):
        needs = _needs(a_max=20, b_max=20)
        scores = [_score(0, 35.0, 30.0, needs), _score(1, 40.0, 38.0, needs)]
        result = rank_venues(scores, needs)

        self.assertTrue(result.no_fit)
        self.assertIsNotNone(result.notice)
        # The closest options are still offered so the group has something to
        # react to, rather than a blank screen.
        self.assertTrue(result.ordered)
        self.assertEqual(result.ordered[0].venue_index, 0)

    def test_relaxing_a_maximum_turns_a_no_fit_into_a_fit(self):
        tight = _needs(a_max=20, b_max=20)
        widened = _needs(a_max=40, b_max=40)
        minutes = (35.0, 30.0)

        self.assertTrue(rank_venues([_score(0, *minutes, tight)], tight).no_fit)
        self.assertFalse(rank_venues([_score(0, *minutes, widened)], widened).no_fit)

    def test_an_unroutable_venue_is_reported_not_ranked(self):
        needs = _needs()
        result = rank_venues([_score(0, None, None, needs)], needs)
        self.assertTrue(result.no_fit)
        self.assertEqual(result.ordered, [])
        self.assertIn("None of these places could be routed", result.notice)

    def test_a_venue_unroutable_for_one_parent_still_serves_the_other(self):
        needs = _needs()
        score = _score(0, 30.0, None, needs)
        self.assertFalse(score.unroutable)
        self.assertTrue(score.travel[1]["unroutable"])

    def test_the_ranking_order_is_inspectable(self):
        """The brief requires the ordering be configurable and logged, so it has
        to be visible in the breakdown rather than buried in a comparator."""
        score = _score(0, 30.0, 32.0, _needs())
        self.assertIn("rank_order", score.breakdown)
        self.assertEqual(score.breakdown["rank_order"][0], "hard_violations")


class GroupFitLabelTests(unittest.TestCase):
    def test_labels_track_absolute_minutes(self):
        self.assertEqual(group_fit_label(3), "Very even")
        self.assertEqual(group_fit_label(10), "Fairly even")
        self.assertEqual(group_fit_label(20), "Noticeably uneven")
        self.assertEqual(group_fit_label(45), "Significant difference")


# ------------------------------------------------------------- the venue pool

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
    os.environ["REGISTRATION_MODE"] = "invite_only"
    os.environ["ADMIN_API_TOKEN"] = "test-admin"
    os.environ["ROUTING_PROVIDER"] = "mock"
    _reset_modules()
    main = importlib.import_module("main")
    from fastapi.testclient import TestClient
    return TestClient(main.app)


class VenuePoolTests(unittest.TestCase):
    def setUp(self):
        self.client = _fresh_app()
        made = self.client.post("/api/meetups", json={
            "mode": "explore", "categories": [],
            "organiser": {"start": ORIGIN_A, "display_name": "A"},
        }).json()
        self.meetup = made["meetup_id"]
        self.a_token = made["your_join_token"]
        self.b_token = made["participant_invite_token"]
        self.slug = made["results_slug"]
        r = self.client.post(
            f"/api/meetups/{self.meetup}/participants/{self.b_token}",
            json={"start": ORIGIN_B, "display_name": "B"},
        )
        self.assertEqual(r.status_code, 200, r.text)

    def tearDown(self):
        self.client.close()

    def _add(self, token, name, coord):
        return self.client.post(
            f"/api/meetups/{self.meetup}/venues/{token}",
            json={"name": name, "coord": coord},
        )

    def test_both_parents_can_contribute_places(self):
        self.assertEqual(self._add(self.a_token, "Soft Play", VENUE_1).status_code, 200)
        r = self._add(self.b_token, "The Farm", VENUE_2)
        self.assertEqual(r.status_code, 200, r.text)
        names = {c["name"] for c in r.json()["candidates"]}
        self.assertEqual(names, {"Soft Play", "The Farm"})

    def test_the_same_place_added_twice_is_reported_not_duplicated(self):
        self._add(self.a_token, "Soft Play", VENUE_1)
        nearly = {"lat": VENUE_1["lat"] + 0.0002, "lng": VENUE_1["lng"]}
        r = self._add(self.b_token, "Soft Play Centre", nearly)
        self.assertEqual(r.status_code, 409)
        self.assertIn("already on the list", r.json()["detail"])

    def test_a_parent_may_withdraw_their_own_suggestion(self):
        added = self._add(self.a_token, "Soft Play", VENUE_1).json()
        vid = added["candidates"][0]["id"]
        r = self.client.delete(f"/api/meetups/{self.meetup}/venues/{self.a_token}/{vid}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["candidates"], [])

    def test_a_parent_may_not_withdraw_someone_elses(self):
        added = self._add(self.b_token, "The Farm", VENUE_2).json()
        vid = [c for c in added["candidates"] if c["name"] == "The Farm"][0]["id"]
        # A is not the suggester, but A *is* the organiser, so try a third
        # party: B removing a venue A added.
        a_added = self._add(self.a_token, "Soft Play", VENUE_1).json()
        a_vid = [c for c in a_added["candidates"] if c["name"] == "Soft Play"][0]["id"]
        r = self.client.delete(f"/api/meetups/{self.meetup}/venues/{self.b_token}/{a_vid}")
        self.assertEqual(r.status_code, 403)
        self.assertIn("organiser", r.json()["detail"])

    def test_the_organiser_may_withdraw_any_suggestion(self):
        added = self._add(self.b_token, "The Farm", VENUE_2).json()
        vid = [c for c in added["candidates"] if c["name"] == "The Farm"][0]["id"]
        r = self.client.delete(f"/api/meetups/{self.meetup}/venues/{self.a_token}/{vid}")
        self.assertEqual(r.status_code, 200, r.text)

    def test_who_suggested_what_is_visible(self):
        r = self._add(self.a_token, "Soft Play", VENUE_1).json()
        card = r["candidates"][0]
        self.assertTrue(card["added_by_you"])
        # And not "yours" when the other parent looks at it.
        other = self.client.get(f"/api/meetups/{self.meetup}/{self.b_token}").json()
        self.assertFalse(other["candidates"][0]["added_by_you"])


class CandidateGenerationTests(VenuePoolTests):
    def test_every_pooled_venue_gets_a_time_for_every_parent(self):
        self._add(self.a_token, "Soft Play", VENUE_1)
        self._add(self.b_token, "The Farm", VENUE_2)

        r = self.client.post(f"/api/meetups/{self.meetup}/candidates/{self.a_token}")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["status"], "ready")
        self.assertEqual(len(body["candidates"]), 2)

        for card in body["candidates"]:
            self.assertEqual(len(card["participant_travel"]), 2,
                             "each parent needs their own number")
            for leg in card["participant_travel"]:
                self.assertGreater(leg["direct_minutes"], 0)
            self.assertGreaterEqual(card["fairness_spread_minutes"], 0)
            self.assertTrue(card["group_fit_label"])

    def test_generation_waits_for_the_second_parent(self):
        client = _fresh_app()
        made = client.post("/api/meetups", json={
            "mode": "explore", "categories": [],
            "organiser": {"start": ORIGIN_A},
        }).json()
        client.post(f"/api/meetups/{made['meetup_id']}/venues/{made['your_join_token']}",
                    json={"name": "Soft Play", "coord": VENUE_1})
        r = client.post(
            f"/api/meetups/{made['meetup_id']}/candidates/{made['your_join_token']}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Waiting for the other parent", r.json()["notice"])
        client.close()

    def test_generation_with_an_empty_pool_asks_for_places(self):
        r = self.client.post(f"/api/meetups/{self.meetup}/candidates/{self.a_token}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Add a few places", r.json()["notice"])

    def test_results_link_shows_the_times_without_exposing_origins(self):
        self._add(self.a_token, "Soft Play", VENUE_1)
        self.client.post(f"/api/meetups/{self.meetup}/candidates/{self.a_token}")

        r = self.client.get(f"/api/meetups/results/{self.slug}")
        self.assertEqual(r.status_code, 200)
        raw = r.text
        for value in (ORIGIN_A["lat"], ORIGIN_A["lng"], ORIGIN_B["lat"], ORIGIN_B["lng"]):
            self.assertNotIn(str(value), raw)
        card = r.json()["candidates"][0]
        self.assertEqual(len(card["participant_travel"]), 2)

    def test_a_vote_survives_regeneration_but_a_withdrawn_venue_takes_its_votes(self):
        added = self._add(self.a_token, "Soft Play", VENUE_1).json()
        vid = added["candidates"][0]["id"]
        self.client.post(f"/api/meetups/{self.meetup}/candidates/{self.a_token}")

        v = self.client.put(
            f"/api/meetups/{self.meetup}/votes/{vid}",
            params={"join_token": self.a_token}, json={"value": "works"},
        )
        self.assertEqual(v.status_code, 200, v.text)
        self.assertEqual(v.json()["candidates"][0]["your_vote"], "works")

        self.client.delete(f"/api/meetups/{self.meetup}/venues/{self.a_token}/{vid}")
        after = self.client.get(f"/api/meetups/{self.meetup}/{self.a_token}").json()
        self.assertEqual(after["candidates"], [])


if __name__ == "__main__":
    unittest.main()

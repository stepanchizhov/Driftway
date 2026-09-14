"""
Step 1: ownership is derived on the server, and export/erasure reach it.

Before this, MeetupParticipant.user_id and MeetupSession.owner_user_id existed
as columns that nothing ever assigned, and favourites were keyed by a random
per-device id the client supplied. Export and erasure both filter on exactly
those links, so both operated on an empty set while reporting success.

The risks these cover, in order of how much damage each would do:

  * one account reading, claiming or deleting another account's records
  * a device's saved places being absorbed into whichever account signed in
    most recently on a shared browser
  * an expired token silently demoting a write to an anonymous one, filing a
    parent's saved place under an id they can no longer see
  * erasure reporting success while leaving precise origins behind
  * a still-valid token continuing to work after the account it names is gone

Tokens are signed with a throwaway RSA key and verified against a stubbed
JWKS, so the real verification path runs without a tenant. This does NOT
demonstrate a live Auth0 integration.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from test_identity_auth0 import (  # noqa: E402
    ADMIN,
    _fresh,
    _token,
)

ALICE = "auth0|alice"
BOB = "auth0|bob"

WINDSOR = {"lat": 51.4857, "lng": -0.6214}
MAIDENHEAD = {"lat": 51.5216, "lng": -0.7205}


def auth(token):
    return {"Authorization": f"Bearer {token}"}


class OwnershipTestCase(unittest.TestCase):
    def setUp(self):
        self.client, self.db = _fresh()

    def tearDown(self):
        self.client.close()

    # -- helpers ---------------------------------------------------------

    def admit(self, sub, name="A Parent"):
        """Mint an invite and redeem it as `sub`. Returns that sub's token."""
        minted = self.client.post(
            "/api/admin/beta-invites", headers={"X-Admin-Token": ADMIN}
        ).json()
        token = _token(sub=sub, email=f"{sub.split('|')[1]}@example.com")
        r = self.client.post(
            "/api/auth/accept-beta-invite",
            json={"invite_token": minted["invite_token"], "display_name": name},
            headers=auth(token),
        )
        self.assertEqual(r.status_code, 200, r.text)
        return token

    def make_meetup(self, token=None, start=None):
        r = self.client.post(
            "/api/meetups",
            json={"mode": "explore", "categories": [],
                  "organiser": {"start": start or WINDSOR,
                                "display_name": "Organiser"}},
            headers=auth(token) if token else {},
        )
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def export(self, token):
        r = self.client.get("/api/account/export", headers=auth(token))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()


# ---------------------------------------------------------------- meetups

class MeetupOwnershipTests(OwnershipTestCase):
    def test_creating_signed_in_puts_the_meetup_in_your_export(self):
        token = self.admit(ALICE)
        self.make_meetup(token)
        data = self.export(token)
        self.assertEqual(len(data["meetup_participation"]), 1)
        # The exact origin is the point: it is the sensitive value, and it is
        # the requester's own, so it belongs in their export.
        self.assertAlmostEqual(
            data["meetup_participation"][0]["exact_start"]["lat"],
            WINDSOR["lat"], places=4)

    def test_creating_signed_out_still_works_and_links_nothing(self):
        """No account is required to plan a meetup, and that must stay true."""
        made = self.make_meetup()
        self.assertIn("your_join_token", made)
        token = self.admit(ALICE)
        # A meetup created anonymously is not retroactively attributed to the
        # next person who signs in.
        self.assertEqual(self.export(token)["meetup_participation"], [])

    def test_joining_signed_in_claims_the_seat(self):
        token_a = self.admit(ALICE)
        made = self.make_meetup(token_a)
        token_b = self.admit(BOB, "Other Parent")
        r = self.client.post(
            f"/api/meetups/{made['meetup_id']}/participants/"
            f"{made['participant_invite_token']}",
            json={"start": MAIDENHEAD, "display_name": "Other Parent"},
            headers=auth(token_b),
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(self.export(token_b)["meetup_participation"]), 1)

    def test_a_forwarded_invitation_cannot_take_a_claimed_seat(self):
        """Holding the link is not enough to overwrite who already filled it in."""
        token_a = self.admit(ALICE)
        made = self.make_meetup(token_a)
        token_b = self.admit(BOB, "Other Parent")
        join_url = (f"/api/meetups/{made['meetup_id']}/participants/"
                    f"{made['participant_invite_token']}")
        self.client.post(join_url, json={"start": MAIDENHEAD},
                         headers=auth(token_b))

        token_c = self.admit("auth0|carol", "Third Parent")
        r = self.client.post(join_url, json={"start": WINDSOR},
                             headers=auth(token_c))
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("another account", r.json()["detail"])
        # And Bob's origin is untouched.
        self.assertAlmostEqual(
            self.export(token_b)["meetup_participation"][0]
            ["exact_start"]["lng"], MAIDENHEAD["lng"], places=4)

    def test_a_guest_with_the_link_still_joins_without_any_account(self):
        token_a = self.admit(ALICE)
        made = self.make_meetup(token_a)
        r = self.client.post(
            f"/api/meetups/{made['meetup_id']}/participants/"
            f"{made['participant_invite_token']}",
            json={"start": MAIDENHEAD, "display_name": "Guest"},
        )
        self.assertEqual(r.status_code, 200, r.text)

    def test_an_organiser_export_excludes_the_other_parents_origin(self):
        token_a = self.admit(ALICE)
        made = self.make_meetup(token_a)
        self.client.post(
            f"/api/meetups/{made['meetup_id']}/participants/"
            f"{made['participant_invite_token']}",
            json={"start": MAIDENHEAD, "display_name": "Guest"},
        )
        body = repr(self.export(token_a))
        self.assertNotIn(str(MAIDENHEAD["lng"]), body)


# ------------------------------------------------------------- favourites

FAV = {"duration_minutes": 30, "distance_km": 12.0, "road_profile": "quiet",
       "character": "lanes", "maps_url": "https://example.test/x"}


class FavouriteOwnershipTests(OwnershipTestCase):
    def test_saving_signed_in_is_account_scoped_and_exported(self):
        token = self.admit(ALICE)
        r = self.client.post("/api/favourites",
                             json={"owner": "device-1", "label": "Loop", **FAV},
                             headers=auth(token))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["scope"], "account")
        self.assertEqual(len(self.export(token)["favourites"]), 1)

    def test_saving_signed_out_stays_on_the_device_and_is_not_exported(self):
        self.client.post("/api/favourites",
                         json={"owner": "device-1", "label": "Loop", **FAV})
        token = self.admit(ALICE)
        self.assertEqual(self.export(token)["favourites"], [])

    def test_the_device_id_in_the_body_cannot_choose_the_owner(self):
        """A signed-in write is filed against the account, whatever is sent."""
        token_a = self.admit(ALICE)
        token_b = self.admit(BOB, "Bob")
        # Alice saves while claiming to be some other owner id.
        self.client.post("/api/favourites",
                         json={"owner": "anything-at-all", "label": "Mine", **FAV},
                         headers=auth(token_a))
        self.assertEqual(len(self.export(token_a)["favourites"]), 1)
        self.assertEqual(self.export(token_b)["favourites"], [])

    def test_one_account_cannot_list_anothers_by_passing_their_id(self):
        token_a = self.admit(ALICE)
        self.client.post("/api/favourites",
                         json={"owner": "device-1", "label": "Alice's", **FAV},
                         headers=auth(token_a))
        alice_id = self.client.get("/api/auth/me",
                                   headers=auth(token_a)).json()["id"]

        token_b = self.admit(BOB, "Bob")
        r = self.client.get(f"/api/favourites?owner={alice_id}",
                            headers=auth(token_b))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), [])

    def test_a_signed_in_list_shows_device_rows_marked_but_unclaimed(self):
        self.client.post("/api/favourites",
                         json={"owner": "device-1", "label": "Older", **FAV})
        token = self.admit(ALICE)
        rows = self.client.get("/api/favourites?owner=device-1",
                               headers=auth(token)).json()
        self.assertEqual([r["scope"] for r in rows], ["device"])
        # Visible, but still not the account's until asked for.
        self.assertEqual(self.export(token)["favourites"], [])

    def test_claiming_is_explicit_repeatable_and_needs_an_account(self):
        self.client.post("/api/favourites",
                         json={"owner": "device-1", "label": "Older", **FAV})
        anon = self.client.post("/api/favourites/claim?owner=device-1")
        self.assertEqual(anon.status_code, 401)

        token = self.admit(ALICE)
        first = self.client.post("/api/favourites/claim?owner=device-1",
                                 headers=auth(token))
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(len(first.json()), 1)
        self.assertEqual(len(self.export(token)["favourites"]), 1)

        # Running it again moves nothing and breaks nothing.
        again = self.client.post("/api/favourites/claim?owner=device-1",
                                 headers=auth(token))
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json(), [])
        self.assertEqual(len(self.export(token)["favourites"]), 1)

    def test_claiming_cannot_reach_another_accounts_rows(self):
        token_a = self.admit(ALICE)
        self.client.post("/api/favourites",
                         json={"owner": "device-1", "label": "Alice's", **FAV},
                         headers=auth(token_a))
        alice_id = self.client.get("/api/auth/me",
                                   headers=auth(token_a)).json()["id"]

        token_b = self.admit(BOB, "Bob")
        r = self.client.post(f"/api/favourites/claim?owner={alice_id}",
                             headers=auth(token_b))
        # Either refused outright or a no-op, but never a transfer.
        self.assertEqual(len(self.export(token_a)["favourites"]), 1)
        self.assertEqual(self.export(token_b)["favourites"], [])
        self.assertIn(r.status_code, (200, 403, 404, 422))

    def test_one_account_cannot_delete_anothers_row(self):
        token_a = self.admit(ALICE)
        made = self.client.post(
            "/api/favourites",
            json={"owner": "device-1", "label": "Alice's", **FAV},
            headers=auth(token_a)).json()
        alice_id = self.client.get("/api/auth/me",
                                   headers=auth(token_a)).json()["id"]

        token_b = self.admit(BOB, "Bob")
        r = self.client.delete(
            f"/api/favourites/{made['id']}?owner={alice_id}",
            headers=auth(token_b))
        self.assertEqual(r.status_code, 404)
        self.assertEqual(len(self.export(token_a)["favourites"]), 1)


# ------------------------------------------------- credentials and failure

class CredentialFailureTests(OwnershipTestCase):
    def test_an_expired_token_fails_the_save_rather_than_going_anonymous(self):
        """The silent-demotion bug: the parent would never see this row again."""
        dead = _token(sub=ALICE, expired=True)
        r = self.client.post("/api/favourites",
                             json={"owner": "device-1", "label": "Loop", **FAV},
                             headers=auth(dead))
        self.assertEqual(r.status_code, 401, r.text)
        # And nothing was written under the device id either.
        self.assertEqual(
            self.client.get("/api/favourites?owner=device-1").json(), [])

    def test_a_garbage_token_is_refused_on_read_too(self):
        r = self.client.get("/api/favourites?owner=device-1",
                            headers={"Authorization": "Bearer not-a-token"})
        self.assertEqual(r.status_code, 401)

    def test_no_credentials_at_all_is_an_ordinary_anonymous_request(self):
        r = self.client.get("/api/favourites?owner=device-1")
        self.assertEqual(r.status_code, 200)

    def test_an_expired_token_does_not_demote_a_meetup_join_to_guest(self):
        token_a = self.admit(ALICE)
        made = self.make_meetup(token_a)
        r = self.client.post(
            f"/api/meetups/{made['meetup_id']}/participants/"
            f"{made['participant_invite_token']}",
            json={"start": MAIDENHEAD},
            headers=auth(_token(sub=BOB, expired=True)),
        )
        self.assertEqual(r.status_code, 401, r.text)


# ---------------------------------------------------------------- erasure

class ErasureTests(OwnershipTestCase):
    def test_erasure_removes_the_things_that_are_actually_linked(self):
        token = self.admit(ALICE)
        self.make_meetup(token)
        self.client.post("/api/favourites",
                         json={"owner": "device-1", "label": "Loop", **FAV},
                         headers=auth(token))
        self.client.post("/api/feedback",
                         json={"owner": "device-1", "route_id": "r1",
                               "predicted_minutes": 30, "actual_minutes": 31,
                               "would_use_again": True},
                         headers=auth(token))

        before = self.export(token)
        self.assertEqual(len(before["meetup_participation"]), 1)
        self.assertEqual(len(before["favourites"]), 1)
        self.assertEqual(len(before["route_feedback"]), 1)

        r = self.client.delete("/api/account", headers=auth(token))
        self.assertEqual(r.status_code, 200, r.text)
        removed = r.json()["removed"]
        self.assertEqual(removed["participations"], 1)
        self.assertEqual(removed["favourites"], 1)
        self.assertEqual(removed["feedback"], 1)

    def test_a_still_valid_token_does_not_survive_the_account(self):
        """The stale-token question: signing in again must not resurrect access."""
        token = self.admit(ALICE)
        self.client.delete("/api/account", headers=auth(token))
        # Same token, cryptographically fine, but names nobody now.
        self.assertEqual(
            self.client.get("/api/account/export", headers=auth(token)).status_code,
            401)
        self.assertEqual(
            self.client.post("/api/auth/session", headers=auth(token)).status_code,
            403)

    def test_erasing_one_parent_leaves_the_other_parents_records(self):
        token_a = self.admit(ALICE)
        token_b = self.admit(BOB, "Bob")
        made = self.make_meetup(token_a)
        self.client.post(
            f"/api/meetups/{made['meetup_id']}/participants/"
            f"{made['participant_invite_token']}",
            json={"start": MAIDENHEAD}, headers=auth(token_b))

        self.client.delete("/api/account", headers=auth(token_b))
        # Alice is untouched and still has her own participation.
        self.assertEqual(len(self.export(token_a)["meetup_participation"]), 1)

    def test_device_rows_are_not_destroyed_by_an_unrelated_erasure(self):
        """Someone else's anonymous device data is not this account's to delete."""
        self.client.post("/api/favourites",
                         json={"owner": "shared-device", "label": "Theirs", **FAV})
        token = self.admit(ALICE)
        self.client.delete("/api/account", headers=auth(token))
        rows = self.client.get("/api/favourites?owner=shared-device").json()
        self.assertEqual(len(rows), 1)

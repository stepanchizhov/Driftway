"""
Stable and Driftway Next share one database (docs/CHANNELS.md). Next runs
newer code, so the database can carry columns, tables and migration steps the
stable code has never heard of. These check, on a disposable SQLite file,
that stable code still reads and writes its records, keeps ownership rules,
and exports and erases an account in full when that has happened - additive
schema is the rule, and this is the behaviour that makes it enough.

Nothing here touches a real database.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text  # noqa: E402

from test_identity_auth0 import _fresh, _token  # noqa: E402

FAV = {"duration_minutes": 30, "distance_km": 12.5, "road_profile": "quiet",
       "maps_url": "https://www.google.com/maps/dir/?api=1"}


def auth(token):
    return {"Authorization": f"Bearer {token}"}


class NewerSchemaTests(unittest.TestCase):
    def setUp(self):
        self.client, self.path = _fresh(REGISTRATION_MODE="open")
        self.alice, self.bob = _token(sub="auth0|alice"), _token(sub="auth0|bob")
        for t in (self.alice, self.bob):
            r = self.client.post("/api/auth/accept-beta-invite", json={}, headers=auth(t))
            self.assertEqual(r.status_code, 200, r.text)
        self.save(self.alice)              # written before Next changed anything

    def tearDown(self):
        self.client.close()

    def save(self, token):
        r = self.client.post("/api/favourites", json={**FAV, "owner": "device-x"},
                             headers=auth(token))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def next_changes_the_schema(self):
        """What a newer release on Next is allowed to do: add a column to
        tables stable uses, add a table, and record a migration step stable
        does not know."""
        from core.db import engine
        with engine.begin() as conn:
            conn.execute(text('ALTER TABLE favourites ADD COLUMN next_only_note VARCHAR(40)'))
            conn.execute(text('ALTER TABLE user_accounts ADD COLUMN next_only_flag BOOLEAN'))
            conn.execute(text('CREATE TABLE next_only_things (id VARCHAR(36) PRIMARY KEY)'))
            conn.execute(text("INSERT INTO schema_migrations (step_id, applied_at) "
                              "VALUES ('9999_from_next', CURRENT_TIMESTAMP)"))
            # A row Next wrote, with its own column filled in.
            conn.execute(text("UPDATE favourites SET next_only_note = 'n'"))

    def test_stable_keeps_working_after_next_adds_to_the_schema(self):
        self.next_changes_the_schema()
        from core.migrations import run_migrations
        self.assertEqual(run_migrations(), [])            # unknown step ignored, nothing re-run
        mine = self.client.get("/api/favourites", params={"owner": "device-x"},
                               headers=auth(self.alice))
        self.assertEqual(mine.status_code, 200, mine.text)
        self.assertEqual(len(mine.json()), 1)             # Next's row, read by stable
        self.save(self.alice)                             # and stable can still write
        self.assertEqual(len(self.client.get("/api/favourites", params={"owner": "device-x"},
                                             headers=auth(self.alice)).json()), 2)

    def test_ownership_holds_across_the_newer_schema(self):
        self.next_changes_the_schema()
        theirs = self.client.get("/api/favourites", params={"owner": "device-x"},
                                 headers=auth(self.bob))
        self.assertEqual(theirs.status_code, 200)
        self.assertEqual(theirs.json(), [])               # Alice's drive is not Bob's

    def test_export_and_erasure_stay_complete(self):
        self.next_changes_the_schema()
        export = self.client.get("/api/account/export", headers=auth(self.alice))
        self.assertEqual(export.status_code, 200, export.text)
        gone = self.client.delete("/api/account", headers=auth(self.alice))
        self.assertEqual(gone.status_code, 200, gone.text)
        from core.db import engine
        with engine.begin() as conn:
            left = conn.execute(text("SELECT COUNT(*) FROM favourites WHERE next_only_note = 'n'")).scalar()
        self.assertEqual(left, 0)                         # Next's row went with the account
        self.assertEqual(self.client.get("/api/account/export", headers=auth(self.alice)).status_code, 401)
        # Bob is untouched.
        self.assertEqual(self.client.get("/api/account/export", headers=auth(self.bob)).status_code, 200)


if __name__ == "__main__":
    unittest.main()

"""
Drives recorded for analysis by maintainers only (core/drive_records.py;
founder, 17 Oct 2026). A maintainer is an account whose email is in
MAINTAINER_EMAILS; anyone else's request to record is ignored. Synthetic
accounts and places; the simulator routes.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from test_identity_auth0 import _fresh  # noqa: E402

DRIVE = {"start": {"lat": 51.4857, "lng": -0.6214}, "target_minutes": 30, "record": True}


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.client, _ = _fresh(configured=False)
        from core.accounts import UserAccount
        from core.db import SessionLocal
        self.s = SessionLocal()
        self.maint = UserAccount(email="maint@example.test", status="active")
        self.other = UserAccount(email="someone@example.test", status="active")
        self.s.add_all([self.maint, self.other])
        self.s.commit()

    def tearDown(self):
        self.s.close()
        self.client.close()

    def as_(self, account):
        return mock.patch("routes.api.current_account", lambda *a, **k: account)

    def records(self):
        from core import drive_records
        return drive_records.all_since(self.s)

    def test_a_maintainers_drive_is_recorded_and_nobody_elses(self):
        with mock.patch.dict(os.environ, {"MAINTAINER_EMAILS": "maint@example.test"}):
            with self.as_(self.other):
                self.assertEqual(self.client.post("/api/generate", json=DRIVE).status_code, 200)
            self.assertEqual(self.records(), [])
            with self.as_(self.maint):
                r = self.client.post("/api/generate", json=DRIVE)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(all(o.get("full_geometry") is None for o in r.json()["routes"]))  # not sent back
        rec = self.records()
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0]["user_id"], self.maint.id)
        self.assertEqual(rec[0]["request"]["target_minutes"], 30)
        self.assertTrue(rec[0]["drives"] and "waypoints" in rec[0]["drives"][0])

    def test_not_recorded_unless_asked(self):
        with mock.patch.dict(os.environ, {"MAINTAINER_EMAILS": "maint@example.test"}), self.as_(self.maint):
            self.client.post("/api/generate", json={**DRIVE, "record": False})
        self.assertEqual(self.records(), [])

    def test_records_go_with_the_account_and_are_in_its_export(self):
        from core import drive_records, retention
        with mock.patch.dict(os.environ, {"MAINTAINER_EMAILS": "maint@example.test"}), self.as_(self.maint):
            self.client.post("/api/generate", json=DRIVE)
        self.assertEqual(len(retention.export_account(self.s, self.maint.id)["drive_records"]), 1)
        removed = retention.erase_account(self.s, self.maint.id)
        self.assertEqual(removed["drive_records"], 1)
        self.assertEqual(drive_records.all_since(self.s), [])

    def test_kept_thirty_days(self):
        import datetime as dt
        from core import drive_records
        with mock.patch.dict(os.environ, {"MAINTAINER_EMAILS": "maint@example.test"}), self.as_(self.maint):
            self.client.post("/api/generate", json=DRIVE)
        row = self.s.query(drive_records.DriveRecord).one()
        row.created_at = dt.datetime.utcnow() - dt.timedelta(days=31)
        self.s.commit()
        self.assertEqual(drive_records.purge(self.s), 1)

    def test_the_app_learns_who_is_a_maintainer(self):
        from core.drive_records import is_maintainer
        with mock.patch.dict(os.environ, {"MAINTAINER_EMAILS": " Maint@Example.test ,x@y.z"}):
            self.assertTrue(is_maintainer(self.maint))
            self.assertFalse(is_maintainer(self.other))
        self.assertFalse(is_maintainer(self.maint))              # not configured: nobody

    def test_only_the_founder_reads_them(self):
        with mock.patch.dict(os.environ, {"ADMIN_API_TOKEN": "founder"}):
            self.assertEqual(self.client.get("/api/admin/drive-records").status_code, 403)
            r = self.client.get("/api/admin/drive-records?since=2026-10-01", headers={"X-Admin-Token": "founder"})
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()

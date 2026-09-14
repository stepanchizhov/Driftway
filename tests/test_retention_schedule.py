"""
Retention as a behaviour rather than a policy.

The functions have existed and been unit-tested since 14 September, but nothing
called them, so nothing expired. These cover the scheduled path: that a run
actually removes expired data, that running it twice is harmless, that it
reports itself so a deployed schedule can be verified rather than assumed, and
that a database failure is a failed run rather than a quiet success.

Also covered: retention and user-requested erasure are separate behaviours, and
both have to work. A purge must not depend on anyone asking.
"""

import importlib
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

BACKEND = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

ADMIN = "retention-admin-token"


def _reset_modules():
    for name in [m for m in sys.modules
                 if m == "main" or m.startswith(("core.", "routes.", "jobs."))]:
        sys.modules.pop(name, None)


def _fresh():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp.name.replace(os.sep, '/')}"
    os.environ["MEET_HALFWAY_ENABLED"] = "true"
    os.environ["ADMIN_API_TOKEN"] = ADMIN
    os.environ["ROUTING_PROVIDER"] = "mock"
    os.environ["REGISTRATION_MODE"] = "invite_only"
    _reset_modules()
    main = importlib.import_module("main")
    from fastapi.testclient import TestClient
    return TestClient(main.app), tmp.name


def _naive_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ScheduledRunTests(unittest.TestCase):
    def setUp(self):
        self.client, self.db = _fresh()
        self.admin = {"X-Admin-Token": ADMIN}

    def tearDown(self):
        self.client.close()

    def _meetup(self, aged_days=0):
        made = self.client.post("/api/meetups", json={
            "mode": "explore", "categories": [],
            "organiser": {"start": {"lat": 51.48, "lng": -0.62}},
        }).json()
        if aged_days:
            from core.db import SessionLocal
            from core.meetups import MeetupSession
            s = SessionLocal()
            row = s.get(MeetupSession, made["meetup_id"])
            row.created_at = _naive_now() - timedelta(days=aged_days)
            s.commit()
            s.close()
        return made

    def test_a_run_removes_an_expired_meetup_and_keeps_a_current_one(self):
        old = self._meetup(aged_days=200)
        fresh = self._meetup()

        r = self.client.post("/api/admin/retention/run", headers=self.admin)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["meetups_purged"], 1)

        # The expired one is gone, including its participants' origins.
        self.assertEqual(
            self.client.get(
                f"/api/meetups/{old['meetup_id']}/{old['your_join_token']}"
            ).status_code, 404)
        self.assertEqual(
            self.client.get(
                f"/api/meetups/{fresh['meetup_id']}/{fresh['your_join_token']}"
            ).status_code, 200)

    def test_running_twice_is_harmless(self):
        self._meetup(aged_days=200)
        first = self.client.post("/api/admin/retention/run",
                                 headers=self.admin).json()
        second = self.client.post("/api/admin/retention/run",
                                  headers=self.admin).json()
        self.assertEqual(first["meetups_purged"], 1)
        self.assertEqual(second["meetups_purged"], 0)

    def test_a_run_does_not_need_anyone_to_ask(self):
        """Retention is separate from user-requested erasure."""
        self._meetup(aged_days=200)
        from core.db import SessionLocal
        from core.retention import purge_expired_meetups
        s = SessionLocal()
        purged = purge_expired_meetups(s)
        s.close()
        self.assertEqual(len(purged), 1)

    def test_health_reports_a_run_so_a_schedule_can_be_verified(self):
        before = self.client.get("/api/health").json()
        self.assertIsNone(before["retention"])

        self.client.post("/api/admin/retention/run", headers=self.admin)
        after = self.client.get("/api/health").json()["retention"]
        self.assertIsNotNone(after)
        self.assertIn("last_run", after)
        self.assertEqual(after["meetups_purged"], 0)
        self.assertFalse(after["backlog"])

    def test_the_run_record_carries_no_personal_detail(self):
        """A log of what was deleted, in detail, would preserve what deletion removed."""
        self._meetup(aged_days=200)
        self.client.post("/api/admin/retention/run", headers=self.admin)
        from core.db import SessionLocal
        from core.retention import last_run
        s = SessionLocal()
        row = last_run(s)
        s.close()
        fields = {c.name for c in row.__table__.columns}
        for forbidden in ("lat", "lng", "email", "token", "display_name",
                          "origin", "user_id"):
            self.assertNotIn(forbidden, " ".join(fields))

    def test_triggering_a_run_requires_the_admin_token(self):
        self.assertEqual(
            self.client.post("/api/admin/retention/run").status_code, 403)
        self.assertEqual(
            self.client.post("/api/admin/retention/run",
                             headers={"X-Admin-Token": "wrong"}).status_code, 403)

    def test_work_is_bounded_so_a_backlog_is_visible(self):
        from core.db import SessionLocal
        from core.meetups import MeetupSession
        from core.retention import MAX_PER_RUN, purge_expired_meetups

        for _ in range(3):
            self._meetup(aged_days=200)
        s = SessionLocal()
        purged = purge_expired_meetups(s, limit=2)
        self.assertEqual(len(purged), 2)
        remaining = s.query(MeetupSession).count()
        s.close()
        self.assertEqual(remaining, 1)
        self.assertGreater(MAX_PER_RUN, 0)


class JobEntryPointTests(unittest.TestCase):
    """The command a scheduler actually runs."""

    def tearDown(self):
        _reset_modules()

    def test_the_job_exits_zero_and_records_the_run(self):
        _client, path = _fresh()
        _client.close()
        job = importlib.import_module("jobs.run_retention")
        self.assertEqual(job.main(), 0)

        from core.db import SessionLocal
        from core.retention import last_run
        s = SessionLocal()
        self.assertIsNotNone(last_run(s))
        s.close()

    def test_an_unreachable_database_is_a_failed_run_not_a_quiet_success(self):
        os.environ["DATABASE_URL"] = "sqlite:////nonexistent-dir/nope.db"
        os.environ["ROUTING_PROVIDER"] = "mock"
        _reset_modules()
        job = importlib.import_module("jobs.run_retention")
        # Non-zero so the scheduler shows red rather than a green tick over
        # a run that deleted nothing because it could not connect.
        self.assertNotEqual(job.main(), 0)
